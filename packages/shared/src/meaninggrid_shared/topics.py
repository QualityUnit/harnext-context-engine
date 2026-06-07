"""Kafka topic names for the Context Management System (CMS).

Internal Kafka is never exposed past the CMS boundary. Events ride these
topics as CloudEvents v1.0 (see envelope.py); the partition key is
``f"{mgtenant}:{subject}"`` so a given entity's events stay ordered within a
consumer group.

Lane split (proposal §"Decision: Kafka direct"):
    cms.events.raw.v1     — ingest firehose (every normalized source event)
    cms.events.fast.v1    — urgent / signal-grade events, published on arrival
    cms.events.batch.v1   — windowed Context Units, published at window close

DLQ is per consumer group: ``{group}.dlq``.
"""

RAW_EVENTS_TOPIC = "cms.events.raw.v1"
FAST_EVENTS_TOPIC = "cms.events.fast.v1"
BATCH_EVENTS_TOPIC = "cms.events.batch.v1"

# Consumer group names (one per role).
CLASSIFIER_GROUP = "cms.classifier"
BUILDER_FAST_GROUP = "cms.builder.fast"
BUILDER_BATCH_GROUP = "cms.builder.batch"

ALL_TOPICS = (RAW_EVENTS_TOPIC, FAST_EVENTS_TOPIC, BATCH_EVENTS_TOPIC)


def dlq_topic_for(group: str) -> str:
    """e.g. dlq_topic_for('cms.builder.fast') -> 'cms.builder.fast.dlq'"""
    return f"{group}.dlq"
