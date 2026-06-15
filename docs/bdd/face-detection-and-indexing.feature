Feature: Face detection and indexing (phase 1)
  As a photographer culling a shoot with Atelier
  I want every photo decoded once, uprighted, and scanned for real human faces
  So that only trustworthy face crops reach clustering, browsing is fast, and
  re-running the indexer never repeats finished work or loses progress.

  Background:
    Given a project with an empty SQLite database at the project path
    And the indexer is invoked with "--photos <root> --db <db>"
    And the detector default gates are in effect:
      | gate                       | value |
      | FACE_DET_THRESHOLD         | 0.65  |
      | FACE_DET_AUTO_ACCEPT       | 0.80  |
      | FACE_MIN_PX                | 32    |
      | FACE_MIN_SHARPNESS         | 0.12  |
      | FACE_MIN_FRONTALITY        | 0.35  |
      | FACE_VERIFY_LANDMARKS      | true  |
    And the analysis long edge is 1536 px

  # ---------------------------------------------------------------- EXIF upright
  @index @exif
  Scenario: A portrait photo rotated by EXIF is processed upright so its face is detected
    Given a JPEG whose pixels are stored sideways with EXIF orientation 6 (rotate 90 CW)
    And the photo contains one clear straight-on face when viewed upright
    When the indexer processes the photo
    Then the image is loaded with the EXIF orientation applied before detection
    And the orientation tag value is stored on the image row
    And the face is detected and one face row is written
    And the stored bbox is in the original (uprighted) image coordinates

  @index @exif
  Scenario: The EXIF orientation is read from the original file, not the transposed copy
    Given a JPEG with EXIF orientation 6
    When the indexer reads the metadata
    Then the orientation column records the original tag value 6
    And the upright image used for detection has no further rotation applied

  # ---------------------------------------------------------------- detector confidence gate
  @index @quality
  Scenario: A detection below the confidence threshold is rejected before clustering
    Given a detection with score 0.60
    When the indexer evaluates the detection
    Then the detection is skipped
    And no face row is written for it

  @index @quality
  Scenario Outline: Detector confidence decides which gates a detection must clear
    Given a detection with score <score> on a square sharp region
    When the indexer evaluates the detection
    Then it is <outcome>
    And the borderline non-face filters are <filters_applied>

    Examples:
      | score | outcome  | filters_applied |
      | 0.60  | rejected | not reached     |
      | 0.70  | gated    | applied         |
      | 0.79  | gated    | applied         |
      | 0.80  | trusted  | skipped         |
      | 0.95  | trusted  | skipped         |

  # ---------------------------------------------------------------- pixel size gate
  @index @quality
  Scenario: A tiny background face below the minimum pixel size is dropped
    Given a detection whose smaller bbox side is 24 px in the analysis image
    When the indexer evaluates the detection
    Then the detection is skipped because min(width, height) is below 32
    And no face row is written for it

  @index @quality
  Scenario: A face exactly at the minimum pixel size is kept
    Given a high-confidence detection whose smaller bbox side is 32 px
    When the indexer evaluates the detection
    Then the size gate passes
    And the detection proceeds to the remaining checks

  # ---------------------------------------------------------------- frontality gate
  @index @quality
  Scenario: A profile face below the frontality threshold is dropped
    Given a detection whose keypoints give a frontality of 0.20
    When the indexer evaluates the detection
    Then the detection is skipped as a profile/ear with an unreliable embedding
    And no face row is written for it

  @index @quality
  Scenario: A high-confidence near-frontal face passes the frontality gate
    Given a detection with score 0.90 whose keypoints give a frontality of 0.50
    When the indexer evaluates the detection
    Then the frontality gate passes
    And because the score is at or above the auto-accept threshold the borderline filters are skipped

  # ---------------------------------------------------------------- sharpness gate
  @index @quality
  Scenario: An out-of-focus face crop below the sharpness floor is dropped
    Given a borderline-or-better detection that passes confidence, size and frontality
    And the full-resolution crop has a squashed sharpness of 0.05
    When the indexer measures the face-crop sharpness
    Then the detection is skipped as an out-of-focus blob
    And no face row is written for it

  @index @quality
  Scenario: A sharp face crop passes the sharpness floor and is stored
    Given a detection that passes confidence, size and frontality
    And the full-resolution crop has a squashed sharpness of 0.40
    When the indexer measures the face-crop sharpness
    Then the sharpness gate passes
    And a face row is written with its confidence, embedding, sharpness and a thumbnail

  # ---------------------------------------------------------------- borderline non-face filters
  @index @quality
  Scenario: A borderline detection with a non-face aspect ratio is dropped
    Given a detection with score 0.70 whose bbox width/height ratio is 2.3
    When the indexer applies the borderline non-face filters
    Then the detection is skipped because the box is not roughly square (0.6..1.7)
    And no face row is written for it

  @index @quality
  Scenario: A borderline detection with impossible keypoint geometry is dropped
    Given a detection with score 0.72 and a roughly-square box
    And its keypoints place the nose above the eyes (anatomically impossible)
    When the indexer applies the borderline non-face filters
    Then the keypoint-plausibility check fails
    And the detection is skipped before the MediaPipe check

  @index @quality
  Scenario: A borderline detection that passes geometry still needs MediaPipe to confirm a face
    Given a detection with score 0.72, a square box and plausible keypoints
    And FACE_VERIFY_LANDMARKS is enabled
    When the indexer runs the MediaPipe second opinion on the padded crop
    And MediaPipe finds no face landmarks on the crop
    Then the detection is skipped as hair/fabric/back-of-head
    And no face row is written for it

  @index @quality
  Scenario: A borderline detection MediaPipe confirms is accepted
    Given a detection with score 0.72, a square box and plausible keypoints
    When MediaPipe finds a face on the padded crop
    And the crop passes the sharpness floor
    Then a face row is written for the detection

  @index @quality
  Scenario: If MediaPipe is unavailable the second-opinion check does not block detection
    Given a borderline detection that passes geometry
    And the MediaPipe landmark model cannot be loaded
    When the indexer runs the second-opinion check
    Then the check returns true rather than raising
    And detection is not blocked by the missing model

  # ---------------------------------------------------------------- trust high confidence
  @index @quality
  Scenario: A high-confidence profile is trusted and kept
    Given a real profile detection with score 0.88 that passes size and frontality
    When the indexer evaluates the detection
    Then the aspect-ratio, keypoint-plausibility and MediaPipe gates are all skipped
    And provided the crop is sharp enough a face row is written

  # ---------------------------------------------------------------- thumbnails
  @index @persistence
  Scenario: A per-image thumbnail is stored so browsing never re-decodes the original
    Given a photo that is successfully processed
    When the image row is written
    Then a JPEG image thumbnail no larger than 360 px on its long edge is stored on the image row
    And each kept face also stores a JPEG crop thumbnail no larger than 256 px
    And later browsing reads thumbnails from the database instead of the original files

  # ---------------------------------------------------------------- JPEG vs PNG metadata
  @index @metadata
  Scenario: A JPEG with EXIF time records a reliable capture time
    Given a JPEG with EXIF DateTimeOriginal, SubSecTimeOriginal and a camera Model
    When the indexer reads the metadata
    Then taken_at is set from EXIF DateTimeOriginal
    And exif_time is stored as 1 (reliable for time-blocking)
    And sub_sec and camera are populated from EXIF

  @index @metadata
  Scenario: A PNG has no EXIF time so capture time falls back to file mtime
    Given a PNG file with no EXIF metadata
    When the indexer reads the metadata
    Then taken_at falls back to the file modification time
    And exif_time is stored as 0
    And camera, sub_sec and orientation are left null
    And the PNG is still detected and indexed normally

  # ---------------------------------------------------------------- resumable indexing
  @index @persistence
  Scenario: Re-running the indexer skips already-processed images
    Given a previous run processed all images and marked them processed=1
    When the indexer is run again over the same folder
    Then only images with processed=0 are selected as pending
    And the already-processed images are not decoded or detected again
    And new images discovered in the folder are enqueued with processed=0 and indexed

  @index @persistence
  Scenario: An image that fails to process is recorded as an error and the run continues
    Given an image that raises while being processed
    When the indexer processes it
    Then the transaction for that image is rolled back
    And the image is marked processed=2 with a truncated error_msg
    And the remaining pending images are still processed

  @index @persistence
  Scenario: Errored images are retried only when --retry-errors is passed
    Given some images are marked processed=2 from a prior run
    When the indexer is run with "--retry-errors"
    Then those images are reset to processed=0 before the pending list is built
    And they are re-processed in this run
    But without "--retry-errors" they remain processed=2 and are skipped

  @index @persistence
  Scenario: Re-indexing an image clears its previous faces and override anchors first
    Given an image that was already indexed with faces and a manual person override on one face
    When the same image is re-processed (e.g. via --retry-errors)
    Then its existing person_overrides rows for those faces are deleted
    And its existing face rows are deleted before new ones are inserted
    And the new face rows are written with fresh ids

  # ---------------------------------------------------------------- CLI overrides
  @index @config
  Scenario Outline: Gate thresholds can be overridden on the command line
    When the indexer is run with "<flag> <value>"
    Then the corresponding gate uses <value> instead of its config default

    Examples:
      | flag             | value |
      | --det-threshold  | 0.50  |
      | --min-px         | 48    |
      | --min-sharpness  | 0.20  |
      | --min-frontality | 0.25  |

  # ---------------------------------------------------------------- empty states
  @index @edge
  Scenario: A folder with no supported images produces an empty but valid index
    Given a photo root containing only non-image files
    When the indexer runs
    Then no images are enqueued
    And the pending count is zero
    And the run finishes reporting 0 indexed, 0 faces and 0 errors

  @index @edge
  Scenario: An image with no detectable faces is still marked processed
    Given a valid photo containing no faces
    When the indexer processes it
    Then the image row is written with face_count 0 and processed=1
    And no face rows are created for it
