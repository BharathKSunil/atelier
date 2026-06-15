Feature: Buckets — user-defined photo collections
  As a photographer culling a shoot
  I want to group photos into named buckets that are separate from my print list
  So that one photo can live in many collections (Social, Candids, Private…) for different purposes

  Buckets are user-defined collections. A photo can belong to MANY buckets at once,
  and buckets are completely independent of the Print list (starring). Each project
  has its own buckets, stored in the per-project SQLite database, so membership
  survives reruns and page reloads. All routes are scoped to a project slug under
  /api/p/<slug>/buckets and require the project to exist.

  Background:
    Given a project "wedding-2026" exists with a populated photo library
    And the project database has migration v7 applied (buckets + bucket_items tables)

  # ---------------------------------------------------------------------------
  # Creation
  # ---------------------------------------------------------------------------

  @api @ui
  Scenario: Create the first bucket gets an auto-assigned colour
    Given the project has no buckets yet
    When I POST /api/p/wedding-2026/buckets with body {"name": "Social media"}
    Then the response status is 200
    And the response is ok true with a numeric "id"
    And the returned "color" is "#c64a5b" (the first palette colour)
    And GET /api/p/wedding-2026/buckets lists exactly one bucket "Social media" with count 0

  @api
  Scenario Outline: Bucket colours cycle through the palette by creation order
    Given the project already has <existing> buckets
    When I POST /api/p/wedding-2026/buckets with body {"name": "<name>"}
    Then the response status is 200
    And the returned "color" is "<color>"

    Examples:
      | existing | name     | color   |
      | 0        | First    | #c64a5b |
      | 1        | Second   | #cda35c |
      | 2        | Third    | #5c9ec6 |
      | 6        | Seventh  | #c64a5b |

  @api
  Scenario: Create a bucket with an explicit colour overrides the palette
    When I POST /api/p/wedding-2026/buckets with body {"name": "Private", "color": "#000000"}
    Then the response status is 200
    And the returned "color" is "#000000"

  @api @validation
  Scenario: Creating a bucket without a name is rejected
    When I POST /api/p/wedding-2026/buckets with body {"name": "   "}
    Then the response status is 400
    And the response is ok false with msg "bucket name is required"
    And no bucket is created

  @ui
  Scenario: Create a bucket from the Buckets tab
    Given I am on the Buckets tab with no buckets
    And the page shows "No buckets yet — create your first one."
    When I click "+ New bucket"
    And I enter "Candids" in the name prompt and confirm with "Create"
    Then a toast shows 'Created "Candids"'
    And a coloured tab "Candids" appears and becomes the active bucket
    And the detail bar shows "0 photos"

  @ui @validation
  Scenario: Cancelling or blank-naming the new-bucket prompt creates nothing
    Given I am on the Buckets tab
    When I click "+ New bucket" and dismiss the prompt without entering a name
    Then no bucket is created and no request is sent

  # ---------------------------------------------------------------------------
  # Rename / recolour
  # ---------------------------------------------------------------------------

  @api @ui
  Scenario: Rename and recolour a bucket
    Given a bucket "Candids" with id 5 exists
    When I edit the name field to "Candid moments" and the colour to "#6cae72" and click "Save"
    Then a PUT is sent to /api/p/wedding-2026/buckets/5 with body {"name": "Candid moments", "color": "#6cae72"}
    And the response status is 200 with ok true
    And a toast shows "Saved"
    And the bucket tab now reads "Candid moments" with the new colour dot

  @api @validation
  Scenario: Renaming a bucket to a blank name is rejected
    Given a bucket with id 5 exists
    When I PUT /api/p/wedding-2026/buckets/5 with body {"name": "  "}
    Then the response status is 400
    And the response is ok false with msg "name required"
    And the stored name is unchanged

  @api
  Scenario: Updating only the colour leaves the name untouched
    Given a bucket "Keepers" with id 5 exists
    When I PUT /api/p/wedding-2026/buckets/5 with body {"color": "#a76cc6"}
    Then the response status is 200 with ok true
    And the bucket is still named "Keepers" with colour "#a76cc6"

  # ---------------------------------------------------------------------------
  # Deletion — keeps the photos
  # ---------------------------------------------------------------------------

  @api @ui
  Scenario: Deleting a bucket removes only the bucket, not the photos
    Given a bucket "Social media" with id 3 contains 12 photos
    When I click "Delete" on the bucket and confirm in the danger dialog
    Then a DELETE is sent to /api/p/wedding-2026/buckets/3
    And the response status is 200 with ok true
    And a toast shows "Bucket deleted"
    And the bucket no longer appears in the list
    And all 12 photos still exist in the library
    And those photos remain in any OTHER buckets they were in

  @ui
  Scenario: The delete confirmation reassures the user the photos are safe
    Given a bucket "Private" exists
    When I click "Delete" on the bucket
    Then a confirmation dialog appears saying the photos stay in the library and only the bucket is removed
    And clicking Cancel leaves the bucket intact

  # ---------------------------------------------------------------------------
  # A photo in many buckets
  # ---------------------------------------------------------------------------

  @api @persistence
  Scenario: One photo can belong to many buckets at once
    Given buckets "Social media" (id 1), "Candids" (id 2) and "Private" (id 3) exist
    And image 42 is in none of them
    When I POST /api/p/wedding-2026/buckets/1/toggle with body {"image_id": 42}
    And I POST /api/p/wedding-2026/buckets/2/toggle with body {"image_id": 42}
    And I POST /api/p/wedding-2026/buckets/3/toggle with body {"image_id": 42}
    Then each response is ok true with "in" true
    And GET /api/p/wedding-2026/buckets/for-images?ids=42 returns {"42": [1, 2, 3]}

  @api
  Scenario: Bucket membership is independent of the print list
    Given image 42 is in bucket "Social media" but is NOT starred
    Then the image's print/star state is unaffected by its bucket membership
    And starring or unstarring the image does not change which buckets it belongs to

  # ---------------------------------------------------------------------------
  # Toggle from Review (number keys + chips)
  # ---------------------------------------------------------------------------

  @api @ui
  Scenario: In Review, pressing a bucket's number drops the current frame into it
    Given I am in Review with buckets "Social media" (chip 1) and "Candids" (chip 2)
    And the current hero frame is image 77 and is in no bucket
    When I press the "1" key
    Then a POST is sent to /api/p/wedding-2026/buckets/1/toggle with body {"image_id": 77}
    And the response is ok true with "in" true
    And chip 1 highlights as active and a toast shows "Added to Social media"
    And the frame shows a coloured dot for that bucket

  @ui
  Scenario: Pressing the same number again removes the frame from the bucket
    Given the current hero frame image 77 is already in bucket "Social media" (chip 1)
    When I press the "1" key
    Then the toggle response is ok true with "in" false
    And a toast shows "Removed from Social media"
    And chip 1 is no longer active and the frame's coloured dot for that bucket disappears

  @ui
  Scenario: Clicking a bucket chip in Review toggles the current frame
    Given I am in Review with the hero frame image 77
    When I click the "Candids" chip
    Then the current frame is toggled in/out of "Candids" exactly as the number key would

  @ui
  Scenario Outline: Only number keys 1–9 map to the first nine buckets
    Given I am in Review with at least <index> buckets
    When I press the "<key>" key
    Then the frame is toggled in the bucket at position <index> (1-based)

    Examples:
      | key | index |
      | 1   | 1     |
      | 5   | 5     |
      | 9   | 9     |

  @ui
  Scenario: A tenth-or-later bucket shows a bullet instead of a number and has no key
    Given I am in Review with 10 buckets
    Then the 10th chip shows "•" instead of a digit
    And no number key toggles the 10th bucket

  @ui
  Scenario: Review shows coloured dots for every bucket a frame already belongs to
    Given image 77 is in buckets "Social media" (red) and "Candids" (green)
    When the burst loads in Review
    Then the filmstrip thumbnail for image 77 shows a red dot and a green dot
    And those chips render as active for the hero frame

  @ui
  Scenario: Review with no buckets shows a hint instead of chips
    Given the project has no buckets
    When I open Review
    Then the bucket strip shows "No buckets yet — create them in the Buckets tab, then press 1–9 here."
    And pressing number keys does nothing

  @api @validation
  Scenario: Toggling without an image_id is rejected
    Given a bucket with id 1 exists
    When I POST /api/p/wedding-2026/buckets/1/toggle with body {}
    Then the response status is 400
    And the response is ok false with msg "need image_id"

  # ---------------------------------------------------------------------------
  # Add by face from People
  # ---------------------------------------------------------------------------

  @ui
  Scenario: The bucket picker is a styled modal with an inline + New bucket
    Given buckets "Family" and "Friends" exist
    And I am on the People tab viewing one person
    When I click "Add to bucket…"
    Then a modal titled "Add to bucket" lists each bucket with its colour dot, name and photo count
    And the modal has a "Cancel" button and a "+ New bucket" button
    And pressing Escape or clicking the backdrop closes the picker without adding anything

  @ui @api
  Scenario: Add one person's photos to a bucket by face
    Given a person "Aunt May" appears in 8 distinct photos
    And a bucket "Family" with id 4 exists
    When I open "Add to bucket…" for "Aunt May" and choose "Family"
    Then a POST is sent to /api/p/wedding-2026/buckets/4/add-people with body {"person_ids": [<may_id>]}
    And the response is ok true with "added" 8
    And a toast shows "Added 8 photos to the bucket"

  @ui @api
  Scenario: Add several selected people as a deduped union of their photos
    Given I have grid-selected 3 people in the People tab
    And those people co-appear in some of the same photos
    And a bucket "Group shots" with id 6 exists
    When I click "Add to bucket…" and choose "Group shots"
    Then a POST is sent to /api/p/wedding-2026/buckets/6/add-people with body {"person_ids": [...3 ids]}
    And every photo any of the three people appear in is added once (DISTINCT image_id — no duplicates)
    And the toast names the number of photos and "3 people"

  @ui @api
  Scenario: Create a bucket inline from the picker, then add to it
    Given I am adding a person's photos and the picker is open
    When I click "+ New bucket" and enter "Highlights"
    Then a new bucket "Highlights" is created via POST /api/p/wedding-2026/buckets
    And the picker resolves to the new bucket id and the person's photos are added to it

  @api @validation
  Scenario: Adding people to a bucket that does not exist returns 404
    Given there is no bucket with id 999
    When I POST /api/p/wedding-2026/buckets/999/add-people with body {"person_ids": [1]}
    Then the response status is 404
    And the response is ok false with msg "no such bucket"

  @api @validation
  Scenario: Adding people with no selection is rejected
    Given a bucket with id 4 exists
    When I POST /api/p/wedding-2026/buckets/4/add-people with body {"person_ids": []}
    Then the response status is 400
    And the response is ok false with msg "no people selected"

  # ---------------------------------------------------------------------------
  # Browse + remove
  # ---------------------------------------------------------------------------

  @api @ui
  Scenario: Browse a bucket's photos with pagination, newest-added first
    Given a bucket "Candids" with id 2 contains 130 photos
    When I open the bucket and GET /api/p/wedding-2026/buckets/2/images?offset=0&limit=60
    Then the response has 60 items ordered by most-recently-added first
    And "total" is 130 and "next_offset" is 60
    And scrolling to the sentinel loads the next page until next_offset is null

  @ui @api
  Scenario: Remove a single photo from a bucket
    Given I am browsing bucket "Candids" (id 2) and image 88 is shown
    When I click the "✕" remove button on image 88's card
    Then a POST is sent to /api/p/wedding-2026/buckets/2/toggle with body {"image_id": 88}
    And the card disappears, the bucket count decrements, and a toast shows "Removed from bucket"
    And image 88 still exists in the library and in any other buckets

  @ui
  Scenario: An empty bucket cannot be exported
    Given a bucket "Empty" with 0 photos is open
    Then the "Export…" button is disabled

  # ---------------------------------------------------------------------------
  # Export
  # ---------------------------------------------------------------------------

  @ui @api
  Scenario: Export a bucket's originals to a chosen folder
    Given a bucket "Social media" with id 1 contains 20 photos
    When I click "Export…" and pick a destination folder via the native picker
    Then a toast shows "Copying originals…"
    And a POST is sent to /api/p/wedding-2026/buckets/1/export with the chosen dest
    And the response is ok true with "count" 20, "total" 20 and the resolved "dest"
    And a toast shows "Exported 20 photos → <dest>"
    And the original files are copied (copy2) into the folder ready to zip and share

  @api
  Scenario: Export reports only the files that actually copied
    Given a bucket contains 20 photos but 3 source files are missing on disk
    When I export the bucket to a valid folder
    Then the destination folder is created if needed
    And the response "count" is 17 while "total" is 20

  @api @security
  Scenario: Export to a path outside the allowed roots is rejected
    Given a bucket with id 1 exists
    When I POST /api/p/wedding-2026/buckets/1/export with body {"dest": "/etc"}
    Then the response status is 400
    And the response is ok false with msg "choose a valid destination folder"
    And nothing is copied
    And only destinations under the home dir, the projects dir, /Volumes, /tmp, /private/tmp, /mnt or /media are accepted

  @api @validation
  Scenario: Export with no destination is rejected
    Given a bucket with id 1 exists
    When I POST /api/p/wedding-2026/buckets/1/export with body {}
    Then the response status is 400
    And the response is ok false with msg "choose a valid destination folder"

  # ---------------------------------------------------------------------------
  # Scoping + persistence
  # ---------------------------------------------------------------------------

  @api @security
  Scenario: Bucket routes require an existing project
    When I GET /api/p/no-such-project/buckets
    Then the response status is 404 with description "no project 'no-such-project'"

  @persistence
  Scenario: Bucket membership survives a rerun and reload
    Given image 42 is in buckets "Social media" and "Private"
    When the project is re-run and the page is reloaded
    Then GET /api/p/wedding-2026/buckets/for-images?ids=42 still returns both bucket ids
    And the buckets and their photos are unchanged
