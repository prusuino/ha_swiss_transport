# Contributing

Bug reports, ideas and pull requests are welcome.

## Reporting a problem

Open an issue with the *Bug report* form. The version of the integration, the Home Assistant version and the diagnostics file answer most first questions.

## Pull requests

- Keep a pull request to one topic; a small one is reviewed faster.
- Code, comments and commit messages are in English.
- Texts shown in the interface live in `custom_components/swiss_transport/strings.json` and in `translations/` (de, en, fr, it). A new text needs an entry in each of them.
- Run the tests before you push:

  ```
  pip install pytest pytest-homeassistant-custom-component
  pytest tests
  ```

- Add a line to `CHANGELOG.md` under the next version.
- Do not commit tokens, addresses or coordinates of real places.

## Licence

Contributions are published under the licence of this repository, see `LICENSE`.
