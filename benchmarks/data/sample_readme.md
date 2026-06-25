# Acme Stream Processor v2.4

A streaming record converter: raw events → normalized JSON → Parquet, with pluggable sinks.

## Overview

Acme Stream Processor ingests raw event records from message queues, normalizes them to a
canonical JSON shape, and writes columnar Parquet files partitioned by date. It is built to
run continuously as a worker process with bounded, O(1) memory regardless of stream size — it
streams each batch through the pipeline rather than buffering the whole topic in memory.

The processor is designed for at-least-once delivery semantics. Every batch is checkpointed
only after it is durably written, so a crash replays the last in-flight batch instead of
dropping or duplicating records downstream. Operators typically run one worker per partition
and scale horizontally by adding workers, each claiming a disjoint set of partitions through
the broker's consumer-group protocol.

## Pipeline

```
INGEST → DECODE → NORMALIZE → VALIDATE → PARTITION → WRITE → CHECKPOINT
```

Each stage is independent and restartable, and the stages communicate through bounded in-memory
queues that apply backpressure when a downstream stage falls behind:

- **INGEST** pulls a batch of raw records from the broker for the claimed partitions.
- **DECODE** detects the wire format (JSON Lines, Avro, or Protobuf) and parses each record.
- **NORMALIZE** maps decoded records onto the canonical field schema, coercing types and
  filling defaults for optional fields.
- **VALIDATE** rejects records that violate the schema; rejects are routed to a dead-letter
  topic rather than aborting the batch.
- **PARTITION** groups records by event date so each Parquet file holds a single day.
- **WRITE** appends to the day's Parquet file in the local buffer, rolling to a new file at a
  configurable size threshold.
- **CHECKPOINT** commits the broker offset only after the write is durable.

A failed stage requeues the in-flight batch rather than dropping it, and repeated failures on
the same batch eventually divert it to the dead-letter topic with the failure reason attached.

## Prerequisites

- Python 3.11 or newer
- Apache Arrow 14+ (the Parquet writer links against it)
- A reachable Kafka or Redpanda broker, with a consumer group configured
- A schema registry if you use the Avro or Protobuf input formats
- At least 2 GB of free disk for the local write buffer

## Installation

Clone the repository, create a virtual environment, and install in editable mode:

```bash
git clone https://example.com/acme/stream-processor.git
cd stream-processor
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Then copy the example configuration and set at least the broker address, the topic, and the
output directory:

```bash
cp config.example.toml config.toml
# edit BROKER_URL, TOPIC, OUTPUT_DIR, and (if used) SCHEMA_REGISTRY_URL
```

Verify the install and that the broker and filesystem are reachable:

```bash
acme --version
acme healthcheck
```

The healthcheck confirms broker connectivity, schema-registry reachability, write permissions
on the output directory, and that the buffer disk has free space above the configured floor.

## CLI Usage

All commands use the `acme` entry point. The core command is `run`, intended to run under a
process supervisor that restarts it according to its exit code.

- `acme run` — start the worker loop; processes batches until interrupted.
- `acme run --once` — process a single batch and exit, useful for cron-style or supervised runs.
- `acme run --stages DECODE,NORMALIZE` — run only the named stages, for debugging a pipeline step.
- `acme run --dry-run` — claim a batch and exercise the pipeline but skip the final write.
- `acme replay <checkpoint>` — reprocess starting from a saved checkpoint offset.
- `acme stats` — print throughput, per-stage latency, and consumer lag metrics.
- `acme validate -i sample.json` — validate a single record against the canonical schema.

Exit codes: `0` success, `2` no records currently available, `1` processing error. A supervisor
should restart on `0`, back off and retry on `2`, and alert on repeated `1`s.

## Supported Input Formats

| Format | Description |
|--------|-------------|
| JSON Lines | one JSON object per line; no external schema needed |
| Avro | binary, schema embedded in the message header or fetched from the registry |
| Protobuf | length-delimited frames; schema resolved from the registry by subject |

The decoder sniffs the format from the first bytes of each batch, so a single topic may carry
more than one format during a migration.

## Project Structure

```
stream-processor/
├── acme/
│   ├── ingest/        # broker consumers and offset management
│   ├── decode/        # format detection and parsing
│   ├── normalize/     # canonical-shape mapping and type coercion
│   ├── validate/      # schema validation and dead-letter routing
│   ├── sinks/         # Parquet writer and debug/console writers
│   ├── partition/     # date partitioning and file rolling
│   └── cli/           # entry points and the supervisor-facing run loop
├── tests/
├── config.example.toml
└── pyproject.toml
```

## License

Copyright © Acme, Inc. All rights reserved.
