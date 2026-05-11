"""Kafka topic name constants.

Topic taxonomy (see docs/architecture/ingestion-pipeline.md §7 and §9.6):
    events.raw.v1            — the firehose
    events.dlq.v1            — global DLQ (processor failures)
    events.dlq.{sink}.v1     — per-sink DLQ (sink failures)
    events.retry.{sink}.{delay}.v1  — per-sink retry tier
"""

RAW_EVENTS_TOPIC = "events.raw.v1"
GLOBAL_DLQ_TOPIC = "events.dlq.v1"


def dlq_topic_for(sink_name: str) -> str:
    """e.g. dlq_topic_for('graphiti') -> 'events.dlq.graphiti.v1'"""
    return f"events.dlq.{sink_name}.v1"


def retry_topic_for(sink_name: str, delay_label: str) -> str:
    """e.g. retry_topic_for('graphiti', '5s') -> 'events.retry.graphiti.5s.v1'"""
    return f"events.retry.{sink_name}.{delay_label}.v1"
