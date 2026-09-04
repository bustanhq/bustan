# Dispatching a delivery agent

One issue, one agent, one branch, one pull request.

## Give it the canonical prompt and nothing else

> You are a delivery agent on the <programme> programme. Your work order is issue
> **#N** in this repository: read it in full, it is self-contained. Then read
> `<path to the backlog>` and follow its "How to use this document" section for the
> rules that apply to every ticket. Do not modify any file outside the issue's `Owns`
> list. When you are done, open one pull request that follows the PR contract and
> includes `Closes #N`.

Resist adding context here. Anything you say in the dispatch prompt is invisible to
every reviewer who later reads the issue and the pull request, so a ticket that only
works because of a side instruction is a ticket that cannot be reassigned, audited, or
reused. If the agent needs to know something, it belongs in the issue.

Two adaptations are legitimate, because they are facts about where the work happens
rather than about what the work is:

- **A base branch that is not the default.** Say which branch the pull request opens
  against, because the agent's tooling will assume the default.
- **A shared document that is not on the agent's branch.** Say which branch to read it
  from.

Make both of these true in the issue body as well.

## Session settings

| Setting | Value |
| --- | --- |
| base revision | the ticket's base branch or tag |
| outcome branch | the ticket's branch name, so the agent's own branch instruction agrees with its issue |
| permission mode | anything except a mode that waits for human approval - an autonomous agent nobody is watching will stall there forever, and a child cannot be granted more than the parent holds |
| title | the ticket id and title, so the session list is readable |
| tags | programme, wave, ticket id |

Record the session id next to the ticket. You will want it when the pull request does
not appear and you need to tell "still working" from "died on turn one".

## After dispatching

Subscribe to the pull request's activity once it opens, so CI failures and review
comments wake you rather than needing a poll.

Webhooks do not cover everything - a first push, a late CI result, and a merge-conflict
transition can all arrive late or not at all. Schedule a check-in far enough out to be
cheap and re-arm it silently while nothing has changed. Do not message anyone to say
nothing happened.

## Dependencies inside a wave

Withhold the dependent ticket's issue until its dependency has merged. Do not dispatch
it with a note telling it to wait: an agent that cannot see the other branch has no way
to know when waiting ended, and an agent that starts anyway will conflict on exactly the
file the dependency was about.

The dispatch is itself the signal that the ground is stable. That is what lets the
ticket be self-contained.
