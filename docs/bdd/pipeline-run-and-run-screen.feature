Feature: Pipeline run and the Run screen
  As a photographer culling a folder of photos in Atelier
  I want to start the four-stage pipeline and watch it progress on the Run screen
  So that I can see what is happening, recover from failures, and re-run only what changed

  Background:
    Given a project "summer-trip" exists with source folder "/photos/summer"
    And I have opened the project's Run screen
    And the pipeline runs four phases in order: index, cluster, series, score
    And each phase runs as a subprocess "python -m atelier.pipeline.<name>"

  # ----------------------------------------------------------------------------
  # Starting a run
  # ----------------------------------------------------------------------------

  @api @happy
  Scenario: Starting a full pipeline run
    Given no run is currently in progress
    When the client sends POST "/api/p/summer-trip/run" with an empty body
    Then the response status is 200
    And the response body has "ok" true and "msg" "started"
    And a new row is recorded in the runs table with status "running"
    And the run executes all four phases index, cluster, series, score in order

  @api @validation
  Scenario: Starting a run with a folder that does not exist
    Given the project's source folder does not point to a real directory
    When the client sends POST "/api/p/summer-trip/run" with an empty body
    Then the response status is 409
    And the response body has "ok" false
    And "msg" reports "folder not found:" followed by the offending path
    And no run is started

  @api @security
  Scenario: Starting a run for an unknown project
    When the client sends POST "/api/p/does-not-exist/run" with an empty body
    Then the request is rejected because the project does not exist

  @ui @happy
  Scenario: The Run screen reflects a running pipeline
    Given a run is in progress on the "index" phase
    When the Run screen renders the latest status
    Then the title shows "Running…"
    And the source line shows "Source: /photos/summer"
    And the "Stop run" button is visible
    And the "Re-run pipeline" button is hidden
    And the one-line summary starts with "Running: Index photos"

  # ----------------------------------------------------------------------------
  # Per-stage cards
  # ----------------------------------------------------------------------------

  @ui
  Scenario Outline: Stage cards reflect each phase's lifecycle state
    Given the "<phase>" stage is in state "<state>"
    When the Run screen renders the stage cards
    Then the "<phase>" card shows the icon "<icon>" and CSS state "<state>"

    Examples:
      | phase   | state    | icon |
      | index   | done     | ✓    |
      | cluster | running  | ●    |
      | series  | queued   | ○    |
      | score   | failed   | !    |

  @ui
  Scenario: A completed phase shows its elapsed time
    Given the "cluster" phase finished and recorded a timing of 12.4 seconds
    When the Run screen renders the stage cards
    Then the "cluster" card shows a duration of "12.4s"

  @ui
  Scenario: A phase that has not started yet is queued while an earlier phase runs
    Given the pipeline is running and currently on the "index" phase
    When the Run screen renders the stage cards
    Then the "cluster", "series", and "score" cards are "queued"
    And the "index" card is "running"

  @ui
  Scenario: Later phases are skipped after a phase fails
    Given the pipeline failed on the "cluster" phase
    When the Run screen renders the stage cards
    Then the "index" card is "done"
    And the "cluster" card is "failed"
    And the "series" and "score" cards are "skipped"

  @ui @progress
  Scenario: The index phase shows done over total with a progress bar
    Given the index phase is running
    And the database has 200 images of which 75 are processed
    When the Run screen renders the index stage card
    Then the index card shows a progress bar filled to 37 percent
    And the index card subtext reads "75/200 images"

  @ui @progress
  Scenario: The index phase surfaces image-level errors in its subtext
    Given the index phase is running
    And the database has 200 images of which 80 are processed and 4 are marked as errors
    When the Run screen renders the index stage card
    Then the index card subtext reads "80/200 images · 4 errors"

  @ui @progress
  Scenario: Non-index running phases show an indeterminate working bar
    Given the "series" phase is running
    When the Run screen renders the series stage card
    Then the series card shows an indeterminate progress bar
    And the series card subtext reads "working…"

  # ----------------------------------------------------------------------------
  # Live counts and face grid
  # ----------------------------------------------------------------------------

  @ui
  Scenario: The live summary and face grid update while running
    Given the run has detected 18 faces so far
    And the run started 90 seconds ago and has not finished
    When the Run screen renders the latest status
    Then the summary includes "18 faces"
    And the summary includes an elapsed time of "1m 30s"
    And the live face count shows 18
    And up to 24 recently detected face thumbnails are shown

  @ui @empty
  Scenario: An idle project with no prior run shows an empty Run screen
    Given the project has never been run
    When the Run screen renders the latest status
    Then the title shows "Run"
    And the summary reads "Idle"
    And the "Re-run pipeline" button is visible
    And the "Stop run" button is hidden

  @ui
  Scenario: A finished run shows completion and re-run controls
    Given all four phases completed successfully
    When the Run screen renders the latest status
    Then the title shows "Complete"
    And the summary starts with "Complete ✓"
    And every stage card is "done"
    And the "Re-run pipeline" button is visible
    And the "Stop run" button is hidden

  # ----------------------------------------------------------------------------
  # Stopping / cancellation
  # ----------------------------------------------------------------------------

  @api @happy
  Scenario: Stopping a running pipeline
    Given a run is in progress
    When the client sends POST "/api/p/summer-trip/run/stop"
    Then the response status is 200
    And the response body has "ok" true and "msg" "stopping"
    And the current phase subprocess is terminated
    And the log records "!! stop requested"
    And the run finishes with status "cancelled" and error "run stopped"

  @api @edge
  Scenario: Stopping when no run is in progress
    Given no run is currently in progress
    When the client sends POST "/api/p/summer-trip/run/stop"
    Then the response status is 409
    And the response body has "ok" false and "msg" "no run in progress"

  @ui
  Scenario: The Stop button reflects a stopped run
    Given a run was stopped by the user
    When the Run screen renders the latest status
    Then the title shows "Stopped"
    And the summary reads "Stopped"
    And the error line shows "run stopped"

  @ui
  Scenario: Clicking Stop disables the button briefly to prevent double-clicks
    Given a run is in progress
    When I click "Stop run"
    Then the button is disabled immediately
    And a toast confirms stopping is underway
    And the button re-enables after about 1.5 seconds

  # ----------------------------------------------------------------------------
  # Concurrency: a second run is rejected
  # ----------------------------------------------------------------------------

  @api @concurrency
  Scenario: A second run is rejected while one is active
    Given a run is already in progress
    When the client sends POST "/api/p/summer-trip/run" with an empty body
    Then the response status is 409
    And the response body has "ok" false and "msg" "a run is already in progress"
    And the in-progress run continues unaffected

  @ui @concurrency
  Scenario: The UI shows a toast when re-run is rejected as a conflict
    Given a run is already in progress
    When I click "Re-run pipeline"
    And the server responds with 409
    Then a toast reads "A run is already in progress"
    And no new run is started

  # ----------------------------------------------------------------------------
  # Logs
  # ----------------------------------------------------------------------------

  @ui
  Scenario: Logs are hidden behind a collapsible "View logs" section
    Given a run is in progress without errors
    When the Run screen renders
    Then the "View logs" section is collapsed by default
    And expanding it reveals the live log output and a "Pause updates" button

  @ui @failure
  Scenario: The logs auto-open on failure with the captured traceback
    Given the pipeline failed on the "cluster" phase
    And the failed phase exited non-zero with a captured traceback in its last lines
    When the Run screen renders the failure
    Then the error line shows "phase 'cluster' exited with code" and the exit code
    And the error-detail block shows the last 40 lines of the crashed phase's output
    And the "View logs" section is automatically opened

  @api
  Scenario: Fetching the live log incrementally with a cursor
    Given the live log currently holds lines up to sequence 50
    When the client sends GET "/api/p/summer-trip/run/log?since=30"
    Then the response returns only log lines with sequence greater than 30
    And each line is a pair of its sequence number and text

  @api @sse
  Scenario: Streaming live log lines over Server-Sent Events
    Given a run is in progress
    When the client opens GET "/api/p/summer-trip/run/stream?since=0"
    Then the response is "text/event-stream" with caching disabled
    And it first sends a "retry: 3000" hint
    And it emits each new log line as an SSE event with id set to the line sequence
    And when the run finishes and the buffer is drained it emits an "end" event

  @ui @persistence
  Scenario: State and logs persist across a mid-run page reload
    Given a run is in progress and 40 log lines have been produced
    When I reload the page during the run
    Then the Run screen seeds the log by fetching "/api/p/summer-trip/run/log?since=0"
    And the previously buffered log lines are replayed into the view
    And the SSE stream resumes from the last seen sequence
    And the stage cards and live counts reflect the current run state

  @ui
  Scenario: Pausing and resuming live updates
    Given a run is in progress and live updates are flowing
    When I click "Pause updates"
    Then the button label changes to "Resume updates"
    And the SSE stream is closed and status polling stops
    When I click "Resume updates"
    Then the log is re-seeded, the stream reopens, and polling restarts

  @ui @fallback
  Scenario: Polling catches up the log when SSE is unavailable
    Given the browser has no EventSource support or the stream dropped
    And the status reports a higher sequence than the client has seen
    When the status poll runs
    Then the client fetches missing lines via "/api/p/summer-trip/run/log?since=<lastSeq>"
    And appends them to the log view

  # ----------------------------------------------------------------------------
  # Stall watchdog
  # ----------------------------------------------------------------------------

  @edge @watchdog
  Scenario: A stalled phase producing no output is terminated
    Given a phase has produced no output for longer than the stall timeout
    When the watchdog checks the running phase
    Then it logs "!! no output for <timeout>s — terminating stalled phase"
    And it terminates the phase subprocess
    And the run finishes with status "cancelled" and error "run stopped — phase stalled"

  # ----------------------------------------------------------------------------
  # Server-restart reconciliation
  # ----------------------------------------------------------------------------

  @persistence @recovery
  Scenario: A server restart reconciles an interrupted run
    Given a run was recorded as "running" when the server was killed
    When the server restarts and the project's runner is first created
    Then any run still marked "running" is updated to status "interrupted"
    And its finished_at is set if it was not already
    And reconciliation runs only once per runner

  @api @history @persistence
  Scenario: Run history survives a restart and exposes durable per-run logs
    Given several past runs were recorded in the runs table
    When the client sends GET "/api/p/summer-trip/runs"
    Then it returns up to 20 runs newest-first with id, started_at, finished_at, status, phases, and error
    When the client sends GET "/api/p/summer-trip/runs/<id>/log" for a run with a stored log file
    Then the captured per-run log file is returned as "text/plain"

  @api @history @edge
  Scenario: Requesting a log for a run with no stored log file
    Given a recorded run whose log file is missing or was never written
    When the client sends GET "/api/p/summer-trip/runs/<id>/log"
    Then the response status is 404

  # ----------------------------------------------------------------------------
  # Settings-triggered partial reruns
  # ----------------------------------------------------------------------------

  @api @partial-rerun
  Scenario Outline: A settings change triggers only the affected phases
    Given the run request specifies "affects" "<affects>"
    When the client sends POST "/api/p/summer-trip/run"
    Then the pipeline runs exactly the phases <phases> in order
    And the saved settings flags are passed to those phases

    Examples:
      | affects   | phases                            |
      | reindex   | index, cluster, series, score     |
      | recluster | cluster, score                    |
      | regroup   | series, score                     |

  @api @partial-rerun
  Scenario: A run request with no affects key runs the full pipeline
    Given the run request omits the "affects" key
    When the client sends POST "/api/p/summer-trip/run"
    Then the pipeline runs all four phases index, cluster, series, score
