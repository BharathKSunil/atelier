Feature: Projects & dashboard
  As a photographer culling on my own Mac
  I want to create one project per shoot from a source folder and see them on a dashboard
  So that I can index each shoot into its own isolated database and pick up where I left off

  Background:
    Given the Atelier app is running locally and serving the dashboard at "/"
    And every state-changing request carries the per-process token "X-Atelier-Token" injected into the page
    And the projects registry lives under "~/.atelier/" with one database per project at "~/.atelier/<slug>/db.sqlite"

  # ---------------------------------------------------------------------------
  # Creating a project
  # ---------------------------------------------------------------------------

  @ui @api
  Scenario: Create a project from a folder kicks off indexing
    Given I am on the dashboard
    When I click "+ New project"
    And I enter "Maya & Sam — June 2026" as the name
    And I enter "/Users/me/Pictures/maya-sam" as the source folder
    And I click "Create & index"
    Then a POST is sent to "/api/projects" with body {"name":"Maya & Sam — June 2026","folder":"/Users/me/Pictures/maya-sam"}
    And the response is 200 with ok true, run_started true, and a project object
    And the project is assigned a slug derived from the name, e.g. "maya-sam-june-2026"
    And a fresh empty database is materialized at "~/.atelier/<slug>/db.sqlite"
    And the source folder is stored as an absolute path
    And the modal closes and I am navigated to "#/p/<slug>/run" where indexing has started

  @api
  Scenario: Slug collisions get a numeric suffix
    Given a project already exists with slug "summer-trip"
    When I create another project named "Summer Trip" pointing at a valid folder
    Then the new project is assigned the slug "summer-trip-2"
    And both projects keep their own database under "~/.atelier/<slug>/"

  @ui @validation
  Scenario: The create button is guarded when name or folder is missing
    Given I am on the dashboard with the New Project modal open
    When I leave the name or the folder blank
    And I click "Create & index"
    Then no request is sent
    And I see an error toast "Name and folder are both required"

  @api @validation
  Scenario Outline: The server rejects a missing name or an invalid folder
    When a POST is sent to "/api/projects" with name "<name>" and folder "<folder>"
    Then the response status is 400
    And the body has ok false with msg "<msg>"
    And no project is added to the registry

    Examples:
      | name      | folder                  | msg                              |
      |           | /Users/me/Pictures/ok   | project name is required         |
      | Untitled  | /no/such/folder         | folder not found: /no/such/folder|
      | Untitled  |                         | folder not found:                |

  @ui
  Scenario: Choosing a folder with the native picker fills the path field
    Given I am on the dashboard with the New Project modal open
    When I click "Choose…"
    And the native macOS folder dialog returns "/Users/me/Pictures/wedding"
    Then a POST to "/api/fs/choose" responds ok true with that path
    And the source-folder field is populated with "/Users/me/Pictures/wedding"

  @ui
  Scenario: The native folder picker is unavailable off macOS
    Given I am on the dashboard with the New Project modal open
    When I click "Choose…" and the picker is unavailable
    Then the response has ok false with unavailable true
    And I see a toast "Folder picker is macOS-only — type or paste the folder path below"
    And focus moves to the source-folder field so I can paste a path manually

  @ui
  Scenario: Cancelling the native folder picker is silent
    Given I am on the dashboard with the New Project modal open
    When I click "Choose…" and dismiss the native dialog without choosing
    Then the response has ok false with msg "cancelled"
    And no toast is shown and the folder field is unchanged

  @ui
  Scenario: Closing the New Project modal resets and discards input
    Given I have opened the New Project modal and typed a name and folder
    When I click "Cancel" or the close "×" or click outside the modal box
    Then the modal is hidden
    And reopening it shows empty name and folder fields

  # ---------------------------------------------------------------------------
  # Dashboard cards
  # ---------------------------------------------------------------------------

  @ui @api
  Scenario: A finished project shows a cover mosaic and stats
    Given a project "Wedding" with processed photos, faces, persons and multi-frame bursts
    When the dashboard loads via GET "/api/projects"
    Then its card shows up to 3 cover thumbnails sourced from "/api/p/<slug>/image_thumb/<id>"
    And the cover images are the top-print-score processed photos with thumbnails
    And the card shows the people, bursts, and photos counts
    And the bursts count reflects only series with frame_count greater than 1
    And the photos count reflects only images where processed = 1
    And the footer shows a "<N> faces" pill

  @ui
  Scenario: A project that is currently indexing shows the indexing state
    Given a project whose run is in progress
    When the dashboard loads
    Then GET "/api/projects" returns running true for that project
    And the footer shows an "● indexing" pill instead of a faces pill
    And if it has no covers yet the cover area reads "indexing…"

  @ui
  Scenario: A new project with no photos yet shows an empty cover
    Given a project that is not running and has no processed photos
    When the dashboard loads
    Then the cover area reads "no photos yet"
    And the people, bursts, and photos counts all show 0

  @ui
  Scenario: Clicking a card opens its review view
    Given the dashboard shows a project card for slug "wedding"
    When I click anywhere on the card except the Delete button
    Then the location hash becomes "#/p/wedding/review"

  @ui
  Scenario: The dashboard shows an empty state when there are no projects
    Given the registry has no projects
    When the dashboard loads and GET "/api/projects" returns []
    Then I see "No projects yet" with a hint to create one to index a folder of photos

  @ui
  Scenario: The dashboard shows an error state when the server is unreachable
    Given the dashboard is loading
    When GET "/api/projects" fails to reach the server
    Then I see "Couldn’t reach the server" with a hint to make sure Atelier is running, then reload

  # ---------------------------------------------------------------------------
  # Deleting a project
  # ---------------------------------------------------------------------------

  @ui @api
  Scenario: Deleting a project removes only its database, leaving originals untouched
    Given a project "Old Shoot" with slug "old-shoot" that is not running
    When I click "Delete" on its card
    And I confirm the dialog "Delete Old Shoot? Removes its database only — your original photos are untouched."
    Then a DELETE is sent to "/api/projects/old-shoot"
    And the response is 200 with ok true
    And "~/.atelier/old-shoot/" with its database is removed and the registry no longer lists it
    And the photos in the original source folder are not modified or deleted
    And the dashboard re-renders without that card

  @ui
  Scenario: Cancelling the delete confirmation does nothing
    Given a project card with a Delete button
    When I click "Delete" and dismiss the confirmation dialog
    Then no DELETE request is sent and the card remains

  @api @persistence
  Scenario: Deleting is blocked with 409 while a run is in progress
    Given a project "Live Shoot" with slug "live-shoot" whose run is in progress
    When a DELETE is sent to "/api/projects/live-shoot"
    Then the response status is 409
    And the body has ok false with msg "stop the run before deleting"
    And the project and its database still exist

  @ui
  Scenario: A blocked delete surfaces the reason to the user
    Given a project whose run is in progress
    When I confirm deleting it
    And the server responds 409 with msg "stop the run before deleting"
    Then I see an error toast "stop the run before deleting"
    And the card is still shown

  @api
  Scenario: Deleting a non-existent project returns 404
    When a DELETE is sent to "/api/projects/ghost"
    Then the response status is 404
    And the body explains there is no project "ghost"

  # ---------------------------------------------------------------------------
  # Isolation & persistence
  # ---------------------------------------------------------------------------

  @persistence
  Scenario: Each project is isolated in its own database
    Given two projects with slugs "alpha" and "beta"
    When photos are indexed into "alpha"
    Then "alpha" stats come only from "~/.atelier/alpha/db.sqlite"
    And "beta" stats come only from "~/.atelier/beta/db.sqlite"
    And changes in one project never appear in the other

  @persistence
  Scenario: Projects and their stats survive an app restart
    Given I created projects and indexed photos in a previous session
    When I restart Atelier and load the dashboard
    Then GET "/api/projects" lists every project from the registry
    And each card shows its persisted people, bursts, photos, and faces counts

  # ---------------------------------------------------------------------------
  # Security
  # ---------------------------------------------------------------------------

  @security
  Scenario Outline: State-changing project requests require the per-process token
    When a "<method>" request is sent to "<path>" without a valid "X-Atelier-Token"
    Then the response status is 403 with "missing or invalid request token"
    And no project is created or deleted

    Examples:
      | method | path                       |
      | POST   | /api/projects              |
      | DELETE | /api/projects/old-shoot    |

  @security
  Scenario: Requests from a non-local host or cross-origin page are rejected
    When a request reaches "/api/projects" with a host outside {127.0.0.1, localhost, ::1}
    Then the response status is 403 with "non-local host"
    And when a request carries a cross-origin Origin header it is rejected 403 with "cross-origin request blocked"
