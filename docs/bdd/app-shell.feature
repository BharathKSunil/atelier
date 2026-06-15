Feature: App shell — routing, network resilience, notifications, and modal accessibility
  As a photographer using Atelier in a single browser window
  I want the app shell to route me cleanly, warn me when the network or a request fails,
  confirm my actions with non-intrusive toasts, and keep keyboard focus and Escape
  behaving predictably across every overlay
  So that I can trust the tool and never get trapped, lost, or silently disconnected.

  Background:
    Given the Atelier SPA is loaded in the browser
    And the page provides the topbar (brand + breadcrumb + mode tabs), the modal markup,
      the lightbox, and the toasts container

  # ---------------------------------------------------------------------------
  # Offline / online banner
  # ---------------------------------------------------------------------------

  @ui
  Scenario: Going offline shows the offline banner
    Given I am online and no offline banner is visible
    When the browser fires the "offline" event
    Then a banner appears reading
      "You are offline — changes can’t be saved until the connection returns."
    And the banner stays pinned until the connection returns

  @ui
  Scenario: Coming back online hides the offline banner
    Given the offline banner is showing
    When the browser fires the "online" event
    Then the offline banner is hidden
    And no banner element lingers in a visible state

  @ui
  Scenario: The banner element is created once and reused, not duplicated
    When I go offline, then online, then offline again
    Then only a single "net-banner" element ever exists
    And it is toggled hidden or shown rather than recreated each time

  @ui
  Scenario: A page loaded while already offline shows the banner immediately
    Given the network is offline before the app loads
    When the app finishes loading and navigator reports it is offline
    Then the offline banner is shown without waiting for any "offline" event

  @ui
  Scenario: A page loaded while online shows no banner
    Given the network is online when the app loads
    Then no offline banner is shown on load

  # ---------------------------------------------------------------------------
  # Request timeout + retry policy
  # ---------------------------------------------------------------------------

  @api
  Scenario: Every API call aborts after 15 seconds
    Given an API request to a slow endpoint
    When the request has not responded after 15 seconds
    Then the request is aborted via its AbortController
    And the call rejects with an error reading "Request timed out: <path>"
    And the error surfaces to the caller rather than hanging forever

  @api
  Scenario: A caller may shorten or lengthen the timeout per request
    Given a request is made with an explicit "timeout" option
    When that many milliseconds elapse without a response
    Then the request aborts at the caller's timeout instead of the 15-second default

  @api
  Scenario: A request that completes in time clears its abort timer
    Given an API request that responds before the timeout
    When the response arrives
    Then the pending abort timer is cleared
    And the request is never aborted

  @api
  Scenario: A non-OK response surfaces a descriptive error, not a JSON parse crash
    Given the server replies with a non-2xx status and an HTML error page
    When the response is handled
    Then the body text is read (capped at 200 characters) rather than JSON-parsed
    And the call rejects with "HTTP <status> on <path> — <detail>"
    And the error carries the numeric "status"

  @api
  Scenario: Idempotent GET reads are safe to retry
    Given an idempotent GET read such as fetching a project list or a burst's frames
    When the read times out or fails transiently
    Then re-issuing the identical GET is safe because it has no side effects
    And a retried GET can never duplicate or corrupt data

  @api
  Scenario: Mutating verbs are never auto-retried
    Given a mutating request using POST or DELETE — for example star, reject, or toggle
    When that request times out or fails
    Then it is not silently re-sent
    And the failure is surfaced (typically as a sticky error toast) so I can decide
    And no mutation is ever applied twice from a single user action

  @api @security
  Scenario: Mutating requests carry the per-process CSRF token; the timeout still applies
    Given a POST or DELETE request
    Then it is sent with the "X-Atelier-Token" header
    And it is still subject to the same 15-second abort timeout

  # ---------------------------------------------------------------------------
  # Toasts
  # ---------------------------------------------------------------------------

  @ui
  Scenario: A success toast auto-dismisses after about three seconds
    When a success toast such as "Added to print list" is shown
    Then it appears in the toasts container
    And after roughly 3 seconds it fades and removes itself
    And I do not have to click it

  @ui
  Scenario: An error toast is sticky until I click it
    When an error toast such as "Could not update bucket" is shown
    Then it is styled as an error and marked sticky
    And it carries the title "Click to dismiss"
    And it stays on screen until I click it
    And clicking it fades and removes it

  @ui
  Scenario: Multiple toasts stack in the toasts container
    When several toasts are raised in quick succession
    Then each is appended to the toasts container
    And each dismisses on its own schedule (success on a timer, error on click)

  # ---------------------------------------------------------------------------
  # Hash routing
  # ---------------------------------------------------------------------------

  @ui
  Scenario: The root hash shows the dashboard
    When the hash is "#/"
    Then the dashboard screen is shown and the project screen is hidden
    And the breadcrumb and mode tabs are hidden

  @ui
  Scenario: A project hash opens that project's workspace
    Given a project with slug "wedding" exists
    When the hash becomes "#/p/wedding/review"
    Then the project screen is shown and the dashboard is hidden
    And the breadcrumb shows the project's name
    And the mode tabs are shown with "Review" active
    And the Review view is mounted

  @ui
  Scenario Outline: Each known mode maps to its view
    When the hash becomes "#/p/wedding/<mode>"
    Then the "<mode>" tab is active
    And only the "view-<mode>" section is visible

    Examples:
      | mode     |
      | review   |
      | people   |
      | prints   |
      | buckets  |
      | run      |
      | settings |

  @ui
  Scenario: An unknown mode falls back to Review
    When the hash becomes "#/p/wedding/bogus"
    Then the workspace opens in "review" mode
    And the Review tab is the active tab

  @ui
  Scenario: Clicking a mode tab switches the hash
    Given I am on "#/p/wedding/review"
    When I click the "People" tab
    Then the hash becomes "#/p/wedding/people"
    And the route re-renders to the People view

  @ui
  Scenario: Switching modes unmounts the views that need teardown
    Given I am on the Review tab with its keyboard handler bound
    When I switch to another mode
    Then Review is unmounted and its key handler is removed
    And Run and Buckets are likewise unmounted when leaving them

  @ui
  Scenario: The brand and breadcrumb both return to the dashboard
    Given I am inside a project workspace
    When I click the brand "Atelier."
    Then the hash becomes "#/" and the dashboard is shown
    And clicking the breadcrumb does the same

  @ui
  Scenario: An unknown project slug still renders the workspace shell
    When the hash references a slug that the projects list does not contain
    Then the breadcrumb falls back to showing the raw slug
    And the workspace shell still renders without crashing

  # ---------------------------------------------------------------------------
  # Modal focus trap
  # ---------------------------------------------------------------------------

  @a11y @ui
  Scenario Outline: Opening a watched modal traps Tab and focuses its first control
    Given focus is on the "<trigger>" control
    When the "<modal>" modal opens
    Then keyboard focus moves into the dialog
    And pressing Tab past the last control wraps to the first
    And pressing Shift+Tab past the first control wraps to the last
    And focus cannot escape the dialog while it is open

    Examples:
      | modal       | trigger             |
      | modal-new   | + New project       |
      | modal-merge | Merge person        |
      | modal-face  | a face thumbnail    |

  @a11y @ui
  Scenario: Closing a watched modal restores focus to the element that opened it
    Given the "New project" modal was opened from the "+ New project" button
    When the modal is closed
    Then keyboard focus returns to the "+ New project" button
    And the trap's keydown listener is removed

  @a11y @ui
  Scenario: The trap is applied and released by watching the modal's hidden class
    Given the watched modals are observed for class changes
    When a modal loses its "hidden" class it gains the focus trap
    And when it regains "hidden" the trap is released
    So that every open and close call site is covered without bespoke wiring

  @a11y @ui
  Scenario: The styled confirm / prompt dialog traps focus and restores it on close
    Given a styled confirm or prompt dialog is opened
    Then focus moves to the input (for a prompt) or the OK button (for a confirm)
    And Tab and Shift+Tab cycle only within the dialog
    When I confirm, cancel, or press Escape
    Then focus returns to the element that was focused before the dialog opened

  @a11y @ui
  Scenario: The bucket picker traps focus and restores it on close
    Given the "Add to bucket" picker is opened from a People action
    Then focus moves into the picker dialog
    When I choose a bucket, cancel, or press Escape
    Then the picker closes and focus returns to the triggering control

  @a11y @ui
  Scenario: Pressing Enter in a prompt accepts it
    Given a prompt dialog with its text input focused
    When I press Enter
    Then the dialog accepts with the input's current value

  # ---------------------------------------------------------------------------
  # Single Escape — close only the topmost overlay
  # ---------------------------------------------------------------------------

  @a11y @ui
  Scenario: One Escape closes the lightbox first when it is open over a modal
    Given a modal is open
    And the lightbox is open on top of it
    When I press Escape once
    Then only the lightbox closes
    And the modal underneath stays open
    And a second Escape is needed to close the modal

  @a11y @ui
  Scenario: One Escape closes the topmost modal when no lightbox is open
    Given one or more modals are open and the lightbox is closed
    When I press Escape once
    Then the topmost open modal is closed
    And only one overlay closes per press

  @a11y @ui
  Scenario: The styled dialog and bucket picker swallow Escape so nothing behind them closes
    Given a styled confirm, prompt, or bucket picker overlay is open above another modal
    When I press Escape
    Then only that overlay cancels and closes
    And the keypress is stopped in the capture phase
    And the global Escape handler never fires, so the modal behind it stays open

  @a11y @ui
  Scenario: Escape with nothing open is a no-op
    Given no lightbox and no modal are open
    When I press Escape
    Then nothing closes and no error occurs

  # ---------------------------------------------------------------------------
  # Lightbox gallery
  # ---------------------------------------------------------------------------

  @ui
  Scenario: Clicking the Review stage opens a multi-image lightbox seeded at the current frame
    Given a burst with several frames and the hero is the 2nd frame
    When I click the stage image
    Then the lightbox opens showing all burst frames in filmstrip order
    And it starts on the current hero frame
    And each frame's caption shows its print score

  @ui
  Scenario Outline: Arrow keys and the prev / next buttons cycle the gallery
    Given the lightbox is open on a multi-image gallery
    When I <action>
    Then the gallery moves to the "<direction>" image and shows it

    Examples:
      | action                       | direction |
      | press ArrowLeft              | previous  |
      | press ArrowRight             | next      |
      | click the previous (‹) button| previous  |
      | click the next (›) button    | next      |

  @ui
  Scenario: The gallery wraps around at both ends
    Given the lightbox is open on the last image of a multi-image gallery
    When I press ArrowRight
    Then it wraps to the first image
    And from the first image ArrowLeft wraps to the last

  @ui
  Scenario: Prev and next controls are hidden for a single-image lightbox
    Given the lightbox is opened on a single image — for example zooming one frame with Enter
    Then the previous and next buttons are hidden
    And arrow keys leave the single image unchanged

  @ui
  Scenario: Clicking the backdrop closes the lightbox
    Given the lightbox is open
    When I click the backdrop (outside the image and controls)
    Then the lightbox closes
    But clicking the image or a control does not close it

  @a11y @ui
  Scenario: Pressing Escape closes the lightbox
    Given the lightbox is open
    When I press Escape
    Then the lightbox closes via the single global Escape handler

  @ui
  Scenario: The close (×) button closes the lightbox
    Given the lightbox is open
    When I click the close button
    Then the lightbox closes
