# Audio generation during Created Video renders

## Context

A Created Video can queue an immutable render attempt with its own script,
workflow and audio. Preparing replacement speech during that render should
leave the running render's inputs available.

## Decision

A Created Video can generate speech while its active attempts have snapshotted
inputs or have already been accepted by the renderer. The job reports
`generating_tts` while the speech request is pending. Render attempts continue
to report their own progress. When speech finishes, the job returns to the
oldest active render's status if one remains.

Audio versions remain available throughout active renders, including queued
attempts. Deletion checks the persisted attempts while holding the job lock.

## Alternatives

Serializing both operations makes new speech wait for GPU work. A separate
speech-attempt model would support multiple queued speech requests and require
new persistence and recovery logic. This feature keeps one speech request per
job and reuses the existing claim mechanism.

## Consequences and migration

The editor reads render progress from render attempts when the job is generating
speech. Existing attempt snapshots and media references work without a database
migration. An older unsubmitted attempt that still reads live job inputs must
submit or finish before speech can run alongside it.
