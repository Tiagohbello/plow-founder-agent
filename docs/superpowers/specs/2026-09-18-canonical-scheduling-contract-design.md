# Canonical Scheduling Contract

## Goal

Give Founder Agent one normative definition of the contact-scheduling lifecycle,
then enforce its safety-critical transitions in the existing pipeline monitor so
that a contact cannot silently skip holds, a draft, an invitation, or hold
cleanup.

## Scope

This change strengthens the existing `founder-scheduling`, `pipeline-monitor`,
and `external-action` seams. It does not add a scheduler, a second state store,
or a general workflow framework.

The contract applies to contacts in the founder-owned wiki pipeline. It covers
the path from identifying who owes the next action through proposing times,
holding those times, preparing the communication, confirming a chosen time,
and sweeping the unused holds.

## Sources of truth

There is one source of truth for each kind of information:

- `skills/founder-scheduling/SKILL.md` is the sole normative behavior contract.
- The existing SQLite suggestions, drafts, and calendar-operation ledgers are
  authoritative for pending work, approvals, and external effects.
- Each wiki contact page is a human-readable projection of verified calendar
  and communication state. It is not the work queue.
- `README.md` summarizes the lifecycle and points to the canonical contract.
- `pipeline-monitor`, `founder-calendar`, `external-action`, and `gmail` own
  orchestration or provider mechanics and must not redefine scheduling policy.

## Contact lifecycle

For every tracked contact, the agent determines whether the next action belongs
to the founder, the contact, or neither.

1. **Founder owes times.** Select exactly three viable options in the contact's
   timezone. Each option must be backed by one busy, attendee-free tentative
   hold. Prepare the proposal in the existing conversation: always save and
   verify a Gmail draft when Gmail is the appropriate channel, or prepare the exact
   iMessage/Plow message and ask for permission to send when that channel is
   appropriate. Do not send automatically.
2. **Contact owes a reply.** Preserve the proposal and holds. Continue checking
   the linked conversation for new evidence; elapsed time may create a follow-up
   obligation, but must not manufacture a reply or calendar fact.
3. **Contact selects a slot.** The plan must create and verify the real
   invitation for the selected slot and then delete every verified sibling
   hold, including the selected tentative hold. Only after those effects are
   verified may the page become `confirmed` with an empty `holds` field.
4. **Meeting is closed or cancelled.** Reconcile the invitation and remaining
   holds from provider evidence, then project the verified result to the page.

## Automatic-hold boundary

An explicitly enabled pipeline monitor is authorized to create the three
reversible tentative holds when it prepares a new-options proposal. This narrow
authorization applies only when all of the following are true:

- live availability was freshly checked across the founder's visible calendars;
- the three operations exactly match the three options in the prepared draft;
- a Gmail proposal has a verified saved provider draft before any hold claim;
- the events are busy, attendee-free, notification-free tentative holds;
- every write uses the existing `external-action` idempotency and reconciliation
  ledger; and
- the created events are fetched and verified before the wiki is updated.

The authorization does not include sending a proposal, creating an invitation
with attendees, deleting holds, or changing an existing invitation. Those
actions retain their current specific-approval requirements. If any hold is
uncertain, the monitor stops, reconciles the existing operation, and does not
create or send a replacement proposal.

## Executable invariants

`pipeline-monitor` rejects observations that would describe an incomplete
scheduling transition:

- `new_options` requires exactly three hold-creation operations and a prepared
  communication draft.
- The three options and three holds must be concrete and independently
  identifiable with unique targets; duplicate operations are invalid. `hold`
  and `invitation` effects use `create`, while `delete_hold` uses `delete`.
- A Gmail proposal identifies the verified existing thread and can be saved as
  a provider draft under the existing profile preference. A text/Plow proposal
  remains ledger-only and asks for send permission.
- `accepted` requires a real invitation-creation operation unless verified
  evidence shows that invitation already exists.
- `accepted` includes one deletion operation for every live sibling hold. An
  empty calendar plan is invalid.
- Calendar effects remain ordered: verify the invitation before deleting any
  hold. A partial or uncertain result stops later operations.

Each `calendar_plan` entry gains one scheduling-semantic `effect` discriminator:
`hold`, `invitation`, or `delete_hold`. The existing `target`, `operation`, and
`intent` values remain the exact external-action identity. This avoids parsing
free-form intent text or inventing a second plan format. The external-action
guard projects those three existing identity fields when matching an operation
and uses `effect` only to apply the narrow automatic-hold authorization.

The validation remains a small, pure extension of the existing observation
normalization. It does not infer provider facts or execute effects. The existing
calendar-operation ledger permits an unapproved claim only for a `hold` entry
on a pending `new_options` suggestion; every other monitor operation continues
to require the suggestion's specific foreground approval.

The existing contact snapshot supplies the expected sibling-hold count from the
page's semicolon-separated `holds` field. This keeps the current wiki schema and
avoids a second hold model. The validator requires the same number of
`delete_hold` entries; provider read-back remains responsible for proving their
identities and existence.

## Monitoring and due work

The monitor treats durable suggestions and external-action records as work. A
wiki `next_step` is a projection of the current suggestion, never the queue
itself. Each run must reconsider every linked contact using fresh source
evidence, including contacts whose page already contains old advice.

This change defines the ownership rule but does not add a general reminder
engine. Follow-up timing can be added later as another observation action once
there is an agreed cadence; it must use durable due state rather than infer work
from prose.

## Failure handling

Invalid observations fail before a suggestion or draft is persisted. Provider
write uncertainty uses the existing ledgers and stops dependent effects. Wiki
write failure never causes a verified external operation to be repeated; the
projection remains pending until it can be reconciled.

Manual or out-of-band messages and calendar changes are evidence to reconcile,
not permission to repeat an action.

## Documentation ownership

The README will state the four lifecycle invariants and link to
`founder-scheduling`. The scheduling skill will carry the complete operational
contract. Other skills will link to it and describe only their own boundary.
This removes contradictory copies such as “offer N options,” “hold only on an
explicit request,” and monitor prose that forbids the narrowly authorized
automatic holds.

This design document records the architectural decision and its rationale; it
is not an operational instruction source. After implementation, detailed agent
behavior lives only in `founder-scheduling`.

## Testing

Unit tests exercise the real observation validator with literal plans. They
prove rejection of two-option proposals, proposals without a draft, accepted
slots with an empty plan, and accepted slots that omit known sibling-hold
deletions. Positive tests cover a three-hold proposal and an invitation-first
confirmation plan. The repository's complete unittest suite remains the
canonical gate.

## Non-goals

- A new scheduling service or database.
- A configurable number of proposed options.
- Automatic third-party messaging.
- Automatic invitations or hold deletion without specific approval.
- A generalized CRM state machine.
- A follow-up cadence chosen without product input.
