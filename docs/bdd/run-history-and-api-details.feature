Feature: Run history and remaining API-level behaviours
  As the single local user of Atelier
  I want recorded run history, durable per-run logs, deduplicated exports, bucket lookups, paginated bucket browsing, and a sensible dashboard cover
  So that I can audit past runs, recover their logs, share photos safely, and recognise my projects at a glance

  # This file captures the precise API contracts that the deeper code in
  # atelier/runner.py + atelier/server.py + atelier/db.py implements, beyond the
  # UI-level behaviour described in pipeline-run-and-run-screen.feature,
  # buckets.feature, projects-and-dashboard.feature and
  # security-model-and-safe-export.feature. Grounding:
  #   - runs table v6 (db.py): id, started_at, finished_at, status, phases, error, log_file
  #   - Runner.runs / run_log_path / reconcile / _open_log / _close_log (runner.py)
  #   - GET /runs, GET /runs/<rid>/log, POST /persons/<pid>/export,
  #     POST /export/<iid>, GET /buckets/for-images, GET /buckets/<bid>/images,
  #     and the dashboard cover query in GET /api/projects (server.py)

  Background:
    Given the Atelier server is running bound to 127.0.0.1
    And a project "wedding" exists with its own SQLite DB migrated to schema v6 or later
    And the project's files live under "~/.atelier/wedding"
    And run history is recorded in the "runs" table

  # ===========================================================================
  # Run history — GET /api/p/<slug>/runs
  # ===========================================================================

  @api @history @persistence
  Scenario: Run history is returned most-recent-first with the recorded fields
    Given the runs table holds several recorded runs
    When the client sends GET "/api/p/wedding/runs"
    And it returns at most 20 rows ordered by id descending (most recent first)
    Then each row carries "id", "started_at", "finished_at", "status", "phases", and "error"
    And the newest run appears first in the list

  @api @history @persistence
  Scenario Outline: Every kind of run is persisted in the runs table
    Given a "<kind>" run is started covering phases "<phases>"
    When the run is recorded at start
    Then a row is inserted with status "running" and phases "<phases>"
    And when the run ends the same row is updated with finished_at and final status

    Examples:
      | kind     | phases                        |
      | full     | index,cluster,series,score    |
      | recluster| cluster,score                 |
      | regroup  | series,score                  |

  @api @history @persistence
  Scenario: The phases column records exactly the phases that ran
    Given a partial run is started for the affected phases "series,score" only
    When the run start is recorded
    Then the runs row "phases" column is the comma-joined list "series,score"
    And only those phases execute as subprocesses

  @api @history
  Scenario: A run that completes is recorded as done
    Given a full run finishes with every phase exiting zero
    When the run end is recorded
    Then the runs row "status" becomes "done"
    And "finished_at" is set to the completion time
    And "error" is null

  @api @history
  Scenario: A run that fails records the error on its row
    Given a run whose "cluster" phase exits non-zero
    When the run end is recorded
    Then the runs row "status" becomes "error"
    And the runs row "error" reads "phase 'cluster' exited with code" and the exit code

  @api @history @edge
  Scenario: A project that has never been run returns an empty history
    Given a freshly created project "blank" with no recorded runs
    When the client sends GET "/api/p/blank/runs"
    Then the response is an empty JSON list

  @api @history @edge
  Scenario: A history read that hits a DB error returns an empty list rather than failing
    Given the runs query cannot be executed against the project DB
    When the client sends GET "/api/p/wedding/runs"
    Then the runner returns an empty list and the endpoint responds 200

  # ===========================================================================
  # Server-restart reconciliation
  # ===========================================================================

  @persistence @recovery
  Scenario: A run left "running" after a crash is reconciled to "interrupted"
    Given the runs table contains a row with status "running" and no finished_at
    When the server restarts and the project's runner is first obtained
    Then that row's status is updated to "interrupted"
    And its "finished_at" is set with COALESCE so any existing value is preserved
    And a run still genuinely in progress is the only thing left as "running"

  @persistence @recovery
  Scenario: Reconciliation runs only once per runner instance
    Given a runner has already reconciled interrupted runs
    When reconciliation is invoked again on the same runner
    Then it returns immediately without touching the runs table
    And starting a new run also triggers reconciliation exactly once

  # ===========================================================================
  # Durable per-run logs — GET /api/p/<slug>/runs/<int:rid>/log
  # ===========================================================================

  @api @history @persistence
  Scenario: Each run writes a durable timestamped per-run log file
    Given a run with run_id 1700000000000 is started
    When the runner opens its log
    Then it creates "~/.atelier/wedding/runs/" if missing
    And it appends to "~/.atelier/wedding/runs/1700000000000.log"
    And each log line is prefixed with a local "%H:%M:%S " timestamp
    And the file is opened in append mode and never truncated

  @api @history @persistence
  Scenario: The latest run is mirrored to run.log for quick tailing
    Given a run finishes and its per-run log file exists
    When the runner closes the log
    Then it copies the per-run log to "~/.atelier/wedding/run.log"
    And the per-run file under "runs/" is left intact as the durable record

  @api @history
  Scenario: Fetching a past run's log streams it as plain text
    Given a recorded run whose "log_file" points at an existing file
    When the client sends GET "/api/p/wedding/runs/<rid>/log"
    Then the response status is 200
    And the body is the file's contents with mimetype "text/plain"
    And undecodable bytes are replaced rather than raising

  @api @history @edge
  Scenario Outline: A past-run log request 404s when the log cannot be served
    Given "<situation>"
    When the client sends GET "/api/p/wedding/runs/<rid>/log"
    Then the response status is 404

    Examples:
      | situation                                                        |
      | the run id matches no row in the runs table                      |
      | the row exists but its log_file column is empty                  |
      | the row's log_file path no longer exists on disk                 |

  @api @history @security
  Scenario: A past-run log request for an unknown project is rejected
    When the client sends GET "/api/p/no-such-project/runs/1/log"
    Then the request is rejected because the project does not exist

  # ===========================================================================
  # Per-person export — POST /api/p/<slug>/persons/<pid>/export
  # ===========================================================================

  @api @export
  Scenario: Exporting a person copies the distinct originals they appear in
    Given person 7 appears in faces across images with paths /src/a.jpg, /src/a.jpg, and /src/b.jpg
    And the client holds the current valid token
    When it sends POST "/api/p/wedding/persons/7/export" with body {"dest":"~/Pictures/p7"} and the valid token
    Then the originals are selected with SELECT DISTINCT so /src/a.jpg is copied once
    And the destination folder is created if it did not exist
    And the response body is {"ok": true, "count": 2, "total": 2, "dest": "<resolved dest>"}

  @api @export @edge
  Scenario: A person export reports count separately from total when a source file is missing
    Given person 7's distinct originals are /src/present.jpg and /src/gone.jpg
    And /src/gone.jpg no longer exists on disk
    And the client holds the current valid token
    When it sends POST "/api/p/wedding/persons/7/export" with a valid destination and the valid token
    Then only /src/present.jpg is copied
    And the response "count" is 1 while "total" is 2
    And the missing source is skipped without failing the request

  @api @export @security
  Scenario Outline: A person export rejects an empty or out-of-root destination
    Given the client holds the current valid token
    When it sends POST "/api/p/wedding/persons/7/export" with body {"dest":"<dest>"} and the valid token
    Then the response status is 400
    And the response body is {"ok": false, "msg": "choose a valid destination folder"}
    And no files are copied

    Examples:
      | dest             |
      |                  |
      | /etc/atelier-pwn |

  # ===========================================================================
  # Single-image export — POST /api/p/<slug>/export/<iid>
  # ===========================================================================

  @api @export
  Scenario: Exporting a single image copies its original to the destination
    Given image 42 has an existing original at /src/forty-two.jpg
    And the client holds the current valid token
    When it sends POST "/api/p/wedding/export/42" with body {"dest":"~/Pictures/one"} and the valid token
    Then the original is copied to "~/Pictures/one/forty-two.jpg"
    And the response body is {"ok": true, "path": "<resolved dest>/forty-two.jpg"}

  @api @export
  Scenario: A single-image export with no dest falls back to ./print_exports
    Given image 42 has an existing original
    And the client holds the current valid token
    When it sends POST "/api/p/wedding/export/42" with an empty body and the valid token
    Then the destination defaults to "./print_exports"
    And that default is still resolved and confined to an allowed root before the copy

  @api @export @edge
  Scenario: A single-image export 404s when the source file is missing
    Given image 42 exists in the DB but its original file is missing from disk
    And the client holds the current valid token
    When it sends POST "/api/p/wedding/export/42" with a valid destination and the valid token
    Then the response status is 404

  @api @export @edge
  Scenario: A single-image export 404s for an unknown image id
    Given no image with id 99999 exists in the DB
    And the client holds the current valid token
    When it sends POST "/api/p/wedding/export/99999" with a valid destination and the valid token
    Then the response status is 404

  @api @export @security
  Scenario: A single-image export to an out-of-root destination is rejected
    Given the client holds the current valid token
    When it sends POST "/api/p/wedding/export/42" with body {"dest":"/etc/x"} and the valid token
    Then the response status is 400
    And the response body is {"ok": false, "msg": "choose a valid destination folder"}

  # ===========================================================================
  # Bucket membership lookup — GET /api/p/<slug>/buckets/for-images
  # ===========================================================================

  @api @buckets
  Scenario: Looking up bucket membership returns an image-id to bucket-id map
    Given image 1 is in buckets 10 and 20, image 2 is in bucket 10, and image 3 is in no bucket
    When the client sends GET "/api/p/wedding/buckets/for-images?ids=1,2,3"
    Then the response maps "1" to [10, 20] and "2" to [10]
    And image 3 is absent from the map because it has no memberships
    And this map drives the Review coloured frame-dots and chip "on" state

  @api @buckets @edge
  Scenario Outline: A membership lookup with no usable ids returns an empty object
    When the client sends GET "/api/p/wedding/buckets/for-images?ids=<ids>"
    Then the response body is {}

    Examples:
      | ids       |
      |           |
      | abc       |
      | ,,        |
      | -1,foo    |

  @api @buckets @edge
  Scenario: Non-numeric tokens are ignored and only digit ids are queried
    Given image 5 is in bucket 30
    When the client sends GET "/api/p/wedding/buckets/for-images?ids=5,foo,7x,8"
    Then only the numeric ids 5 and 8 are used in the query
    And the response maps "5" to [30]

  # ===========================================================================
  # Bucket browse pagination — GET /api/p/<slug>/buckets/<bid>/images
  # ===========================================================================

  @api @buckets @pagination
  Scenario: Bucket images are paginated newest-added first
    Given bucket 2 contains 130 images
    When the client sends GET "/api/p/wedding/buckets/2/images?offset=0&limit=60"
    Then it returns 60 items ordered by added_at descending then id
    And "total" is 130 and "next_offset" is 60
    And each item carries "id", "path", and "print_score"

  @api @buckets @pagination
  Scenario: The default page size is 60 when no limit is given
    Given bucket 2 contains more than 60 images
    When the client sends GET "/api/p/wedding/buckets/2/images"
    Then the offset defaults to 0 and the limit defaults to 60

  @api @buckets @pagination
  Scenario: next_offset is null on the last page
    Given bucket 2 contains 130 images
    When the client sends GET "/api/p/wedding/buckets/2/images?offset=120&limit=60"
    Then it returns the final 10 items
    And "next_offset" is null because offset + limit is not less than total

  @api @buckets @pagination @edge
  Scenario Outline: Pagination params are clamped to a safe range
    When the client sends GET "/api/p/wedding/buckets/2/images?offset=<offset>&limit=<limit>"
    Then the effective offset is <eff_offset> and the effective limit is <eff_limit>

    Examples:
      | offset | limit | eff_offset | eff_limit |
      | -5     | 60    | 0          | 60        |
      | 0      | 9999  | 0          | 500       |
      | 0      | 0     | 0          | 1         |
      | 0      | -3    | 0          | 1         |
      | abc    | xyz   | 0          | 60        |

  @api @buckets @edge
  Scenario: Browsing an empty or unknown bucket returns no items
    Given bucket 999 has no items (or does not exist)
    When the client sends GET "/api/p/wedding/buckets/999/images"
    Then it returns an empty items list with "total" 0 and "next_offset" null

  # ===========================================================================
  # Dashboard cover selection — GET /api/projects
  # ===========================================================================

  @api @dashboard
  Scenario: The cover thumbnails are the top scored processed images with a stored thumbnail
    Given the project has processed images, some with a stored thumbnail and a print_score
    When the client sends GET "/api/projects"
    Then the project's "cover" is the ids of processed images that have a non-null thumbnail
    And they are ordered by print_score descending and limited to 5

  @api @dashboard @fallback
  Scenario: The cover falls back to the first processed images when none are scored with thumbnails
    Given the project has processed images but none with a stored thumbnail
    When the client sends GET "/api/projects"
    Then the cover falls back to the first 5 processed images by natural order

  @api @dashboard @edge
  Scenario: A project with no processed images has an empty cover
    Given the project has no processed images
    When the client sends GET "/api/projects"
    Then the project's "cover" is an empty list
    And a DB error while computing the cover leaves it empty without failing the list

  @ui @dashboard
  Scenario: The dashboard card renders only the first three cover thumbnails
    Given GET "/api/projects" returned up to 5 cover ids for the project
    When the project card renders its cover mosaic
    Then only the first 3 cover ids are shown as thumbnails
    And each thumbnail is sourced from "/api/p/<slug>/image_thumb/<id>"
