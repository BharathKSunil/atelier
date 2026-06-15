Feature: Print list of starred keepers
  As a wedding photographer culling a shoot in Atelier
  I want a print list that gathers every frame I have starred as a keeper
  So that I can review my final selects and copy the originals out to hand off

  The print list is the set of "print" picks (starred keepers). Starring is a
  manual toggle made in Review; a single burst may contribute several keepers.
  Because a wedding can produce thousands of selects, the list is served in
  pages and the UI loads them with infinite scroll. "Export all" copies the
  starred originals into a destination folder. Because the picks are manual,
  they persist across pipeline re-runs.

  Background:
    Given a local project with slug "harper-wedding"
    And the Atelier server is running on a local host
    And the SPA was served with a valid per-process request token
    And I am viewing the Print list view for "harper-wedding"

  # ----------------------------------------------------------------------------
  # Listing the starred keepers
  # ----------------------------------------------------------------------------

  @api @happy
  Scenario: The print list returns every starred keeper as a counted page
    Given 3 images are starred as print keepers
    When the client sends "GET /api/p/harper-wedding/prints?offset=0&limit=60"
    Then the response status is 200
    And the response field "total" is 3
    And the response field "items" contains 3 images
    And each item includes "id", "path", "series_id" and "print_score"
    And the response field "next_offset" is null

  @api
  Scenario: Items are ordered by burst then image id
    Given the following starred images exist
      | id | series_id |
      | 40 | 7         |
      | 12 | 2         |
      | 31 | 7         |
    When the client sends "GET /api/p/harper-wedding/prints?offset=0&limit=60"
    Then the items appear in the order 12, 31, 40
    And images sharing a "series_id" stay grouped together

  @ui @happy
  Scenario: The view header shows how many photos are selected
    Given 248 images are starred as print keepers
    When I open the Print list view
    Then the count header reads "248 photos selected"
    And the "Export all" button is visible

  @ui
  Scenario: The header uses the singular form for a single keeper
    Given exactly 1 image is starred as a print keeper
    When I open the Print list view
    Then the count header reads "1 photo selected"

  # ----------------------------------------------------------------------------
  # Infinite scroll pagination (a wedding can star thousands)
  # ----------------------------------------------------------------------------

  @api @persistence
  Scenario: Paging walks the whole list 60 at a time
    Given 130 images are starred as print keepers
    When the client sends "GET /api/p/harper-wedding/prints?offset=0&limit=60"
    Then the response field "total" is 130
    And the response field "items" contains 60 images
    And the response field "next_offset" is 60
    When the client sends "GET /api/p/harper-wedding/prints?offset=60&limit=60"
    Then the response field "items" contains 60 images
    And the response field "next_offset" is 120
    When the client sends "GET /api/p/harper-wedding/prints?offset=120&limit=60"
    Then the response field "items" contains 10 images
    And the response field "next_offset" is null

  @ui @happy
  Scenario: Scrolling toward the bottom loads the next page automatically
    Given 130 images are starred as print keepers
    And I open the Print list view so the first 60 cards are shown
    When I scroll until the page sentinel comes within 600px of the viewport
    Then the next 60 cards are appended to the grid
    And no full-page reload occurs

  @ui
  Scenario: The sentinel is removed once the final page has loaded
    Given 130 images are starred as print keepers
    And I have scrolled through every page
    Then the loading sentinel is removed from the grid
    And no further "GET .../prints" requests are made while scrolling

  @ui
  Scenario: A short list shows no sentinel because there is nothing more to load
    Given 12 images are starred as print keepers
    When I open the Print list view
    Then all 12 cards are shown
    And the loading sentinel is not present

  @api
  Scenario Outline: Out-of-range paging parameters are clamped to safe values
    Given 5 images are starred as print keepers
    When the client sends "GET /api/p/harper-wedding/prints?offset=<offset>&limit=<limit>"
    Then the response status is 200
    And the effective offset used is <eff_offset>
    And the effective limit used is <eff_limit>

    Examples:
      | offset | limit | eff_offset | eff_limit |
      | -10    | 60    | 0          | 60        |
      | 0      | 9000  | 0          | 500       |
      | 0      | 0     | 0          | 1         |
      | abc    | xyz   | 0          | 60        |

  @ui @error
  Scenario: A failed first load shows a retry-friendly message
    Given the prints endpoint is unreachable
    When I open the Print list view
    Then I see "Couldn't load the print list"
    And I am told to check the connection and try again

  @ui @error
  Scenario: A failed page append warns without losing the cards already shown
    Given 130 images are starred as print keepers
    And the first 60 cards are shown
    When scrolling triggers the next page request and it fails
    Then a toast reads "Could not load more"
    And the 60 cards already on screen remain visible

  # ----------------------------------------------------------------------------
  # Opening a frame
  # ----------------------------------------------------------------------------

  @ui
  Scenario: Clicking a thumbnail opens the full image in the lightbox
    Given the print list shows a card for image 12 at "renee/IMG_012.RAF"
    When I click the thumbnail
    Then the lightbox opens the full image for image 12
    And the caption shows the file name "IMG_0012.RAF"

  @ui
  Scenario Outline: Keyboard users can open a frame from its thumbnail
    Given the print list shows a card for image 12
    When I focus the thumbnail and press "<key>"
    Then the lightbox opens the full image for image 12

    Examples:
      | key   |
      | Enter |
      | Space |

  # ----------------------------------------------------------------------------
  # Removing a photo from the list (unstar)
  # ----------------------------------------------------------------------------

  @ui @happy
  Scenario: Removing a card un-stars the keeper and refreshes the list
    Given 3 images are starred as print keepers
    And the print list shows a card for image 31
    When I click the "✕" remove control on image 31's card
    Then "POST /api/p/harper-wedding/star/31" is sent
    And a toast reads "Removed"
    And the list re-renders with image 31 no longer present
    And the count header now reads "2 photos selected"

  @api
  Scenario: Un-starring the last keeper toggles the pick off
    Given image 31 is the only starred print keeper
    When the client sends "POST /api/p/harper-wedding/star/31"
    Then the response status is 200
    And the response field "starred" is false
    And a later "GET .../prints" returns "total" 0

  @ui @error
  Scenario: A failed removal keeps the photo in the list
    Given the print list shows a card for image 31
    And the star endpoint will fail
    When I click the "✕" remove control on image 31's card
    Then a toast reads "Could not remove"
    And image 31 remains in the list

  @ui
  Scenario: An emptied list falls back to the empty-state prompt
    Given exactly 1 image is starred as a print keeper
    When I remove that photo from the print list
    Then the list re-renders to the empty state
    And I see "Nothing selected yet"
    And I am prompted to "Star frames in Review to build your print list."

  # ----------------------------------------------------------------------------
  # Export all
  # ----------------------------------------------------------------------------

  @ui @happy
  Scenario: Export all copies the starred originals into the project export folder
    Given 3 images are starred and their original files exist on disk
    When I click "Export all"
    Then "POST /api/p/harper-wedding/prints/export" is sent
    And the originals are copied into "./print_exports/harper-wedding"
    And the existing files keep their metadata timestamps
    And a toast reads "Exported 3 photos → <dest>"

  @api
  Scenario: Export reports only the files it could actually copy
    Given 4 images are starred
    And 1 of those original files is missing from disk
    When the client sends "POST /api/p/harper-wedding/prints/export"
    Then the response status is 200
    And the response field "count" is 3
    And the response field "dest" ends with "print_exports/harper-wedding"

  @api @security
  Scenario: Export refuses a destination outside the allowed roots
    When the client sends "POST /api/p/harper-wedding/prints/export" with body
      """
      { "dest": "/etc/atelier-out" }
      """
    Then the response status is 400
    And the response field "ok" is false
    And the response field "msg" is "choose a valid destination folder"
    And no files are written outside the allowed roots

  @ui
  Scenario: The empty list offers no export action
    Given no images are starred as print keepers
    When I open the Print list view
    Then I see "Nothing selected yet"
    And the count header is blank
    And the "Export all" button is hidden

  # ----------------------------------------------------------------------------
  # Manual picks survive a re-run
  # ----------------------------------------------------------------------------

  @persistence
  Scenario: Starred keepers are manual and remain after re-running the pipeline
    Given 3 images are starred as print keepers
    When I re-run the Atelier pipeline for "harper-wedding"
    Then the same 3 images are still starred
    And every print pick has source "manual"
    And the pipeline did not add or drop any starred keeper

  # ----------------------------------------------------------------------------
  # Security
  # ----------------------------------------------------------------------------

  @security @api
  Scenario: Un-starring without the request token is rejected
    When a request "POST /api/p/harper-wedding/star/31" is sent without the "X-Atelier-Token" header
    Then the response status is 403
    And the keeper remains starred

  @security @api
  Scenario: Exporting from a cross-origin page is blocked even with a guessable URL
    When "POST /api/p/harper-wedding/prints/export" is sent with an Origin from another site
    Then the response status is 403
    And no originals are copied

  @security @api
  Scenario: Requests to a non-local host are refused before any work
    When "GET /api/p/harper-wedding/prints" is sent with a non-local Host header
    Then the response status is 403
