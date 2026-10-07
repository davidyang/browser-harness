# Padlet: open a password-protected board and download post attachments

URL: `https://padlet.com/<owner>/<board-slug>` (school boards also appear as
`https://<school>.padlet.org/<teacher>/<slug>`).

## Password page

- The password input is React-controlled. `fill_input(...)` and setting
  `.value` leave it empty. Click the input's box center, `type_text(password)`,
  confirm `js("document.querySelector('input[type=password]').value")` matches,
  then `press_key("Enter")`.
- Take board passwords from the email that shared the board. Strip `\r`: a
  stray carriage return makes the password wrong without any error message.
- padlet.com is behind Cloudflare. A "Just a moment..." / "Security check"
  page can appear before or after the password. Call `cloudflare_challenge()`
  and wait for David's click (see MACHINE_SETUP.md, "Bot checks and Cloudflare
  challenges").

## Attachments

- The board only shows preview PNGs (`v1.padlet.pics/...url=padlet-artifacts...`)
  of each attachment's first page. They are not the files.
- `padlet_starting_state` holds no post or attachment URLs.
- Open a post by clicking its preview image's box center. The post dialog
  (`[role=dialog]`) has an iframe
  `https://padlet.com/beethoven/pdf-viewer?url=<encoded file URL>`. The `url`
  parameter is the original file on `u1.padletusercontent.com` with an
  `expiry_token`. Plain `curl` can download it until the token expires.
- Close the dialog with its close button (aria-label contains "close") and
  check `[role=dialog]` is gone before clicking the next preview. `Escape` does
  not close it reliably, and the next click then reads the old post's URL.
- The dialog's `innerText` lines give section, subject, and title, which are
  good for naming files.
