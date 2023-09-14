# Technologies choices

## Languages

When we patch and work on any upstream project, the main principle is to adapt to upstream's code style and principles. This could be C/glib, python, Rust, …

However, any new projects we are upstream for should file into one of the bucket of accepted technologies for our team, those are:

* Dart/Flutter for any new GUI.
* Go for any service/command line application.
* Rust, for shared libraries. Some service/command line application or bindings to existing C projects is accepted for experimental purposes.

If you find yourself wanting to implement any new upstream project outside of those technologies, please reach out to your manager to get an approval, with the reasoning behind it.

## Templates

Templates are available for any of those technologies, please, look for [How-to-use-templates.md](How to use our templates) section.

## General design

We need to split internal and external logic. The service / (UI|external stimulies) split approach has been used many times with success inside our team. The main idea is:

* Most of the business logic lives inside the service.
* The UI (CLI, GUI, any exposed API) is clearly defined and contains mostly the graphical representation, piloted by the service itself.

This allows simple mocking between each stacks and easier reuse of our business logic across multiple interface representation.

## APIs

APIs should be versioned. We can consider v0 as unversioned at first for faster development.

> Note that APIs using **protobuf** should not need versioning (even more if used with gRPC), as the syntax enforces backward compatibility rules.

## Inter-process communication

There are 2 technologies that have been currently used in our team for IPC. Those are:

* dbus (linux communication event bus). This one should be used when interoperating with existing services. It supports some priviledge control mechanism and apparmor mediation, which makes it suitable for API access right control in snaps. It should use dbus activation to spin up services at the desired time.
* grpc over unix socket (or tcp). This one helps having a defined and strongly typed API using protobuf. We can only mediate per user (which uid/gid process is talking to my unix socket). It should use unix socket activation to spin up services at the desired time.

> Note: mediation over snap for any API using unix socket: all snap services are root, so service to service communication needs another mediation protocol. FIXME: OPENED_QUESTION
