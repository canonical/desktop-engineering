# Technology choices

## Languages

When patching and working on any upstream project, the main principle
is to adhere to upstream's coding style and principles.  This could be
C/GLib, Python, Rust, etc.

However, for the new projects we are the upstream for, they should
fall under one of the following accepted technology categories for
our team:

* New GUI: Dart/Flutter
* New service/CLI: Go
* New shared libraries, and service/CLI or bindings to an existing
  C project (experimentally): Rust

If you find yourself wanting to implement a new project using
technologies outside of the above, please reach out to your
manager - and explain your reasoning - for an approval.

## Templates

Templates are available for any of the above technologies.
Please see [How to use our templates](how-to-use-templates.md).

## General design

The internal and external logic for a system should be separated.
The service / (UI|external stimuli) split approach has been used
many times with success in the team.  The main idea is:

* Most of the business logic lives inside the service.
* The UI (CLI, GUI, or the exposed API) is clearly defined and
  contains mostly the graphical representation, piloted by the
  service itself.

This allows simple mocking between each stack, and enables easier
reuse of our business logic across multiple interface representations.

## APIs

APIs should be versioned.  `v0` can be used to indicate an unversioned
API at first during the initial development.

> Note that APIs using **protobuf** should not need versioning,
> especially if used with gRPC, as the syntax enforces backward
> compatibility rules.

## Inter-process communication

Two technologies have been used in our team for IPC so far:

* D-Bus (GNU/Linux communication event bus): Should be used when
  interoperating with existing services.  It supports a privileged
  control mechanism and apparmor mediation, which makes it suitable
  for API access control in snaps.  It should use D-Bus activation to
  spin up services when desired.  Please see the article ["How to
  Version D-Bus Interfaces Properly and Why Using / as Service Entry
  Point Sucks"][dbus-versioning] for tips on versioning a D-Bus API.

* gRPC over Unix socket (or TCP): Helps to have a defined and strongly
  typed API using protobuf.  Can only mediate per user (which uid/gid
  process is talking to my Unix socket).  It should use Unix socket
  activation to spin up services when desired.

> Note: mediation over snap for any API using Unix socket: all snap
> services are root, so service to service communication needs another
> mediation protocol.  FIXME: OPEN_QUESTION

[dbus-versioning]: https://0pointer.de/blog/projects/versioning-dbus.html
