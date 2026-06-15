Feature: Per-project settings (tuning knobs)
  As a photographer culling a photo project
  I want to tune how faces are detected, grouped into people, and how bursts are formed
  So that I can shape the results to my shoot and re-run only the part of the pipeline I changed

  Background:
    Given a project "Summer Trip" exists with slug "summer-trip"
    And its settings have never been changed, so the project uses built-in defaults

  # ---------------------------------------------------------------------------
  # Reading the settings (spec + values)
  # ---------------------------------------------------------------------------

  @api
  Scenario: Fetching settings returns the knob spec and current values
    When the client sends GET "/api/p/summer-trip/settings"
    Then the response status is 200
    And the body has a "spec" array and a "values" object
    And each spec entry has keys: key, label, group, min, max, step, default, affects, help
    And "values" contains every knob key with its default value

  @api
  Scenario: Knobs are organised into Detection, Clustering and Series groups
    When the client sends GET "/api/p/summer-trip/settings"
    Then the spec contains knobs whose "group" is "Detection"
    And the spec contains knobs whose "group" is "Clustering"
    And the spec contains knobs whose "group" is "Series"

  @api
  Scenario Outline: Each knob declares which re-run it affects
    When the client sends GET "/api/p/summer-trip/settings"
    Then the knob "<key>" is in group "<group>" with affects "<affects>"

    Examples:
      | key              | group      | affects   |
      | det_threshold    | Detection  | reindex   |
      | min_px           | Detection  | reindex   |
      | min_sharpness    | Detection  | reindex   |
      | min_frontality   | Detection  | reindex   |
      | min_cluster_size | Clustering | recluster |
      | min_samples      | Clustering | recluster |
      | selection_epsilon| Clustering | recluster |
      | merge_cosine     | Clustering | recluster |
      | time_gap         | Series     | regroup   |
      | series_cos       | Series     | regroup   |
      | embed_cos        | Series     | regroup   |

  @api
  Scenario: Fetching settings for an unknown project is rejected
    When the client sends GET "/api/p/does-not-exist/settings"
    Then the response status is 404
    And the body description mentions no project "does-not-exist"

  # ---------------------------------------------------------------------------
  # The settings UI
  # ---------------------------------------------------------------------------

  @ui
  Scenario: The settings screen renders one card per knob group with a "Save only" action
    Given I open the Settings screen for "summer-trip"
    Then I see a "Save only" button in the page header
    And I see a "Detection" card, a "Clustering" card and a "Series" card
    And the Detection card's primary button reads "Save & re-index (full)" with the note "re-detects every photo — slow"
    And the Clustering card's primary button reads "Save & re-cluster" with the note "fast — minutes"
    And the Series card's primary button reads "Save & re-group bursts" with the note "fast — minutes"

  @ui
  Scenario: Every knob has a help balloon explaining what it does and its impact
    Given I open the Settings screen for "summer-trip"
    Then every knob shows a focusable "?" help marker
    And hovering or focusing the "?" reveals a balloon describing the knob and its trade-off
    And for "Detection confidence" the balloon explains higher means fewer false positives but may drop real faces, and lower catches more faces but lets in junk

  @ui
  Scenario: The slider and the number box for a knob stay in sync
    Given I open the Settings screen for "summer-trip"
    When I drag the "Detection confidence" slider to 0.6
    Then the "Detection confidence" number box also shows 0.6
    When I type 0.45 into the "Detection confidence" number box
    Then the "Detection confidence" slider also moves to 0.45

  @ui
  Scenario: Settings fail to load
    Given the settings endpoint is unreachable
    When I open the Settings screen for "summer-trip"
    Then I see an empty state reading "Couldn’t load settings"
    And it tells me to check the connection and try again

  # ---------------------------------------------------------------------------
  # Save only (persist without re-running)
  # ---------------------------------------------------------------------------

  @ui @persistence
  Scenario: "Save only" persists values without starting any re-run
    Given I open the Settings screen for "summer-trip"
    And I set "Min cluster size" to 5
    When I click "Save only"
    Then a PUT is sent to "/api/p/summer-trip/settings" with the current values
    And I see a "Settings saved" toast
    And no run is started
    And I remain on the Settings screen

  @ui
  Scenario: "Save only" surfaces a failure
    Given I open the Settings screen for "summer-trip"
    And the settings PUT will fail
    When I click "Save only"
    Then I see a "Could not save settings" error toast

  @api @persistence
  Scenario: Saving clamps each value to that knob's min/max
    When the client sends PUT "/api/p/summer-trip/settings" with values:
      | key              | value |
      | det_threshold    | 9.0   |
      | min_px           | 4     |
      | min_cluster_size | 0     |
      | series_cos       | 0.40  |
    Then the response status is 200
    And the returned "det_threshold" is 0.85
    And the returned "min_px" is 16
    And the returned "min_cluster_size" is 2
    And the returned "series_cos" is 0.5

  @api @security
  Scenario: Saving ignores unknown keys and non-numeric values
    When the client sends PUT "/api/p/summer-trip/settings" with values:
      | key            | value      |
      | det_threshold  | 0.55       |
      | bogus_key      | 1.0        |
      | min_px         | not-a-num  |
    Then the response status is 200
    And the returned values include "det_threshold" of 0.55
    And the returned values do not include "bogus_key"
    And "min_px" remains its default because "not-a-num" could not be parsed

  @api @persistence
  Scenario: Integer knobs are stored as integers
    When the client sends PUT "/api/p/summer-trip/settings" with "min_cluster_size" of 7
    Then the response status is 200
    And the stored "min_cluster_size" is the integer 7

  @api @persistence
  Scenario: Saved settings survive a reload
    Given the client saved "det_threshold" of 0.6 for "summer-trip"
    When the client later sends GET "/api/p/summer-trip/settings"
    Then "values.det_threshold" is 0.6

  @api @persistence
  Scenario: Settings are isolated per project
    Given a second project exists with slug "winter-trip"
    And "summer-trip" has "min_cluster_size" saved as 8
    When the client sends GET "/api/p/winter-trip/settings"
    Then "winter-trip" still reports the default "min_cluster_size"

  @api @security
  Scenario: Saving settings for an unknown project is rejected
    When the client sends PUT "/api/p/ghost/settings" with any values
    Then the response status is 404

  # ---------------------------------------------------------------------------
  # Save & re-run (group actions)
  # ---------------------------------------------------------------------------

  @ui @persistence
  Scenario: "Save & re-index" confirms, persists, runs the full pipeline, and navigates to Run
    Given I open the Settings screen for "summer-trip"
    And I change "Detection confidence" to 0.7
    When I click "Save & re-index (full)"
    Then a confirm dialog "Re-index all photos?" appears warning it re-detects every photo
    When I confirm with "Re-index"
    Then a PUT persists the values to "/api/p/summer-trip/settings"
    And a POST is sent to "/api/p/summer-trip/run" with affects "reindex"
    And I see a "Saved — reindex started" toast
    And I am navigated to "#/p/summer-trip/run"

  @ui
  Scenario: Cancelling the re-index confirm aborts the save and re-run
    Given I open the Settings screen for "summer-trip"
    And I change "Detection confidence" to 0.7
    When I click "Save & re-index (full)"
    And I dismiss the "Re-index all photos?" confirm dialog
    Then no PUT is sent
    And no run is started
    And I remain on the Settings screen

  @ui @persistence
  Scenario: "Save & re-cluster" persists and triggers a re-cluster without a confirm dialog
    Given I open the Settings screen for "summer-trip"
    And I change "Min samples" to 3
    When I click "Save & re-cluster"
    Then no confirm dialog appears
    And a PUT persists the values
    And a POST is sent to "/api/p/summer-trip/run" with affects "recluster"
    And I see a "Saved — recluster started" toast
    And I am navigated to "#/p/summer-trip/run"

  @ui @persistence
  Scenario: "Save & re-group bursts" persists and triggers a re-group
    Given I open the Settings screen for "summer-trip"
    And I change "Burst time gap (s)" to 30
    When I click "Save & re-group bursts"
    Then a PUT persists the values
    And a POST is sent to "/api/p/summer-trip/run" with affects "regroup"
    And I see a "Saved — regroup started" toast
    And I am navigated to "#/p/summer-trip/run"

  @api
  Scenario Outline: The re-run runs only the phases matching the affected group
    When the client sends POST "/api/p/summer-trip/run" with affects "<affects>"
    And no run is already in progress
    Then the response status is 200 and "ok" is true
    And the runner is started with phases "<phases>"

    Examples:
      | affects   | phases                       |
      | reindex   | index, cluster, series, score|
      | recluster | cluster, score               |
      | regroup   | series, score                |

  @api
  Scenario: Starting a re-run while one is already in progress is rejected
    Given a run is already in progress for "summer-trip"
    When the client sends POST "/api/p/summer-trip/run" with affects "recluster"
    Then the response status is 409
    And "ok" is false with a reason message

  @ui
  Scenario: A re-run that the server refuses keeps me on Settings
    Given I open the Settings screen for "summer-trip"
    And a run is already in progress for "summer-trip"
    When I click "Save & re-cluster"
    Then the values are still persisted
    But I see an error toast explaining the run could not start
    And I am not navigated to the Run screen
