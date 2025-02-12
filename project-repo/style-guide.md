Style guide
===========

This document includes a series of guidelines and recommendations for
formatting code and documentation, aimed mainly at the [new] projects
we are the upstream for.  Otherwise, for existing projects and those
where we are not the upstream, the project's existing guidelines and
policies should take precedence over those outlined in this document.

Code
----

For new projects where we are the upstream, we aim to follow community
formatting conventions for the programming language where available.
If the language has tools for automatically formatting code, they
should be used.  For example, for Rust, this would be `rustfmt`; and
for Go, we prefer `gofumt`, a stricter `gofmt`.

Documentation
-------------

For new projects where we are the upstream, please aim to follow these
formatting conventions for markup text:

- Try to limit lines to about 70 characters if the markup language is
  newline-agnostic in paragraph texts, meaning that breaking a long
  line in a paragraph does not affect the generated/rendered output.
  Markdown, reStructuredText, (La)TeX, and HTML are some instances of
  such markup languages.  On the other hand, the MoinMoin wiki syntax
  as seen on the Ubuntu Wiki is sensitive to line breaks, and each
  newline corresponds to a new paragraph.

  Keeping lines short when possible has various advantages, including
  better readability of the text, more readable diffs on GitHub and
  other tools, avoiding line wrapping especially on smaller screens,
  and a clearer view when positioning multiple columns/windows of text
  side-by-side on larger screens.

- Use two spaces (instead of one) at the end of a sentence after the
  ending mark (period, exclamation mark, or question mark) if the
  markup language is space-agnostic, meaning that multiple spaces
  are collapsed to one in the generated/rendered output.  Markdown,
  reStructuredText, (La)TeX, and HTML are some instances of such
  markup languages.

  Using two spaces to separate sentences has several advantages,
  including:

  - Unambiguously separating sentences.  This is especially useful
    when writing prose languages like English where a period might
    appear in the middle of a sentence, for example when using "i.e."
    or "e.g.", and separating sentences with two spaces indicates both
    to the human reader as well as the computer that the sentence has
    ended there.

  - Formatting and text manipulation commands in various text editors
    like GNU Emacs and Vim default to expecting two spaces at the end
    of sentences.  For example, Emacs's `fill-paragraph` and Vim's
    `gqq` (wrap current line) and `gqip` (wrap current paragraph)
    expect sentences to be separated by two spaces.

  - Visually, separating sentences by two spaces makes it easier for
    the human eye to more easily find where a sentence ends and the
    next one begins.  This is especially true when reading text that
    is set in a monospace typeface, as is the case for the majority of
    people who read and write documentation markup in a text editor.
