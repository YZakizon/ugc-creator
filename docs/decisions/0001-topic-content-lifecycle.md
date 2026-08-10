# ADR 0001: Topic and repeatable Content lifecycle

Status: accepted

Date: 2026-08-09

## Context

The original persistence model created a `Batch` containing `TopicJob` rows, with
each job representing a different topic. The product now needs one topic to retain
multiple generated content versions, with repeatable speech and video outputs and
safe deletion of either one version or the complete topic history.

## Decision

For V1, the existing `Batch` record is the durable Topic container and each
`TopicJob` is one numbered Content version. New user-facing `/topics` and
`/contents` endpoints expose those concepts while legacy batch/job endpoints remain
compatible.

`content_number` is unique and monotonically increasing within a Topic. Generating
more content creates a new row and never overwrites prior generated content. One
Content owns multiple archived audio assets and multiple RenderAttempts.

Generated media uses a sanitized topic prefix and stable content/output numbers:

```text
{short-topic}_content{content-number}_{output-number}-audio.mp3
{short-topic}_content{content-number}_{output-number}-video.mp4
```

Content and Topic deletion are blocked while external work is active. Deletion
removes referenced objects through the storage abstraction and then removes the
database records through existing cascades. The final Content cannot be removed
independently; deleting its Topic prevents an empty, unusable history container.

## Alternatives considered

- Introduce new Topic, ContentItem, and RenderJob tables immediately. This would be
  cleaner in isolation but would duplicate current lifecycle data and require a
  risky migration before V1 needs that separation.
- Overwrite one TopicJob on regeneration. This loses comparison history and makes
  media ownership and retries difficult to explain.

## Consequences

- Internal class and table names retain `Batch` and `TopicJob` temporarily.
- New code and UI use Topic and Content vocabulary.
- Existing provider-neutral orchestration and immutable RenderAttempt snapshots are
  unchanged.
- A later model split remains possible if multi-render comparison outgrows attempt
  history, but it is not required for the V1 workflow.
