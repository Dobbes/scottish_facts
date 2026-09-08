# SMS Campaign Resubmission

## Status And Tasks

This is an owner field guide, not a submitted campaign or evidence of carrier approval. On September 8, 2026, the owner confirmed the exact registered identity Elumsden Sole, supplied public support brunslx@gmail.com, and authorized commit, push, and GitHub Pages publication. Publication authorization does not authorize SMS sending, production enablement, or Twilio submission. The intended Pages URLs below are NOT yet published or verified by this update. GitHub CLI is not authenticated, so Pages configuration is blocked; Git push can use its separate existing authentication. Do not infer that Pages is enabled or disabled from this blocker.

The reviewed site and safety changes were committed as `446fada` (`Add verified operator site and messaging safety controls`) and successfully pushed to `origin/main`. Logged-out HTTP checks of all four intended URLs returned 404 on September 8, 2026; the updated site is not verified live. Complete step 2 below to configure Pages, then verify actual deployed content. No Twilio submission, SMS send, production enablement, or secret inspection was performed.

- [x] Add dedicated static home, privacy, terms, and verbal-enrollment pages in `docs/`.
- [x] Add a fixed application-owned STOP footer with complete-message length validation.
- [x] Supply samples using actual reviewed suffixes, field guidance, and a private consent procedure.
- [x] Document a manual enrollment-confirmation procedure; no confirmation CLI or automatic confirmation is implemented.
- [x] Local validation: 175 tests passed; `compileall` and `git diff --check` passed (Git emitted line-ending notices only). Static content/link checks are not a browser rendering or live Pages verification.
- [x] Owner confirms registered identity Elumsden Sole, its operation of Scotland Facts, public support brunslx@gmail.com, and commit/push/Pages authorization.
- [x] Commit and push the 30 reviewed site, documentation, safety, migration, and test files to `origin/main`.
- [ ] Owner publishes reviewed files and verifies all Pages links while logged out.
- [ ] Owner configures and verifies actual STOP/START/HELP behavior and a supported confirmation procedure.
- [ ] Owner updates the campaign fields and resubmits, then waits for approval.
- [ ] Owner completes deployed security, consent, monitoring, and authorization checks before any sending.

Keep `SMS_SEND_ENABLED=false` and `RECIPIENT_CONSENT_CONFIRMED=false` until the applicable consent and authorization steps in `USER_SETUP.md`. This update preserves default-off gates. It does not inspect or change local secrets or hosted sending switches.

## 1. Confirmed Identity And Support

Scotland Facts is operated by Elumsden Sole. The owner explicitly confirmed **Elumsden Sole** as the exact registered identity and supplied **brunslx@gmail.com** for public support. This is owner confirmation, not an independent inspection of Twilio registration records.

The home, privacy, terms, enrollment script, and campaign examples use that relationship consistently. Enter Elumsden Sole wherever the registration asks for the registered operator, and Scotland Facts wherever it asks for the program name. If registration changes, update the disclosures truthfully rather than substituting a GitHub handle.

Public support is [brunslx@gmail.com](mailto:brunslx@gmail.com), not GitHub Issues. Monitor this inbox before each daily send and handle privacy and opt-out requests there or through the existing private enrollment conversation. Do not post recipient information in public issues. Mailbox delivery and monitoring have not been independently tested; no support email was sent by this update.

## 2. Publish The Dedicated Site

The dependency-free site is under `docs/`; `.nojekyll` makes it a plain static Pages site. No application server, online signup form, analytics, or deployment workflow is needed.

1. Review the complete worktree, including prior uncommitted safety changes. Audit intended files for credentials and personal data. Do not use a blanket `git add .`; stage only reviewed, intended files when you decide to commit.
2. Commit and push the reviewed changes using the owner's explicit authorization. Use normal Git authentication; do not extract credentials or start an unattended interactive login.
3. GitHub CLI reports `You are not logged into any GitHub hosts.` The owner can run `gh auth login` themselves and then request completion, or use [repository Pages settings](https://github.com/Dobbes/scottish_facts/settings/pages). Choose **Deploy from a branch**, **main**, and **/docs**. Save. Do not change the daily SMS workflow to publish Pages.
4. Wait for the Pages deployment to finish. Read its reported URL; a custom domain or different repository configuration changes the URLs below.
5. Open each URL in a logged-out/private browser, on desktop and a narrow mobile viewport. Verify HTTP success, readable content, navigation, visible support/privacy/terms links, keyboard focus, and the complete verbal script. Verify that no authentication is needed to read the policies. Check the actual deployed content, not just GitHub's source view.

Intended URLs, NOT yet published or verified:

| Field | Intended URL |
| --- | --- |
| Website | `https://dobbes.github.io/scottish_facts/` |
| Privacy Policy | `https://dobbes.github.io/scottish_facts/privacy/` |
| Terms and Conditions | `https://dobbes.github.io/scottish_facts/terms/` |
| Verbal opt-in evidence / enrollment | `https://dobbes.github.io/scottish_facts/enrollment/` |

Do not resubmit with the repository root as both policy links. Dedicated, directly readable pages address the policy verification problem, but publication alone does not guarantee approval.

## 3. Campaign Fields

Use only after identity, publication, and provider behavior are confirmed. Console labels and requirements vary by sender type and current Twilio registration flow.

| Field | Entry / action |
| --- | --- |
| Program name | `Scotland Facts`; registered operator: `Elumsden Sole`. |
| Description | Scotland Facts is operated by Elumsden Sole. Invitation-only informational/entertainment SMS: source-backed Scotland facts with brief humorous endings, up to one daily fact to one known consenting recipient; no purchased lists or unsolicited marketing. Separate enrollment confirmation and requested service replies may also be sent. Support: brunslx@gmail.com. |
| Website / Privacy / Terms | The distinct, actually verified Pages URLs above, not the source repository root. |
| Opt-in method / message flow | Verbal consent in a direct conversation. Operator identifies themselves and the sender, provides published terms/privacy links, reads the public enrollment script, waits for explicit affirmative agreement, and records dated consent privately before enabling messaging. Cite the deployed enrollment URL. No online form or keyword signup. |
| Opt-in keywords | `Not applicable - verbal enrollment only`, if explanatory text is accepted. If the field only accepts actual keywords and is optional, leave it empty and explicitly explain verbal enrollment in the message flow. Do not invent START or another enrollment keyword to fill a blank. If mandatory, ask Twilio how to represent verbal-only enrollment. |
| Opt-in confirmation | Use the confirmation template below only once the manual provider procedure is available and adopted. A populated field does not implement sending. Do not claim the application automatically sends it. |
| Opt-out keywords / message | Match the actual sender/provider configuration, including mandatory native behavior. Do not claim all possible keywords are enabled merely because the application bans them from jokes. |
| HELP keywords / message | Match the actual sender/provider configuration. Include Scotland Facts and monitored support brunslx@gmail.com in the response, where customization is supported. Generic HELP with no usable support route needs resolution. |

If the form asks about embedded links or phone numbers in messages, distinguish daily facts (no URLs or phone numbers) from HELP/service templates (the support email). Answer for the messages the campaign actually covers; these templates do not include a website URL or support phone number.

Daily sample 1 (application format, reviewed suffix):

```text
SCOTLAND FACTS: Scotland's national animal is the unicorn. The unicorns have declined to comment. Reply STOP to opt out.
```

Daily sample 2 (application format, reviewed suffix):

```text
SCOTLAND FACTS: The Forth Bridge opened in 1890. The bagpipe committee considers this progress. Reply STOP to opt out.
```

These are format examples, not a claim that the samples were sent or freshly researched in this update. Both pass application suffix and final-body validation. Daily messages remain one line, URL-free, emoji-free, and at most 300 Unicode characters including the fixed footer; that can still be multiple billable SMS segments.

## 4. Enrollment Confirmation Choice

**Not implemented in the application:** there is no confirmation command, automatic welcome message, consent-log storage, or confirmation send ledger in PostgreSQL. `subscription renew` does not send anything. Adding a second send path would need its own persisted at-most-once boundary; do not improvise it using `run` or reuse/reset a daily key.

For this one-recipient program, use a single-operator, private, provider-controlled manual confirmation procedure. Before resubmission, verify with Twilio that the current sender/account has a supported way to send this approved transactional confirmation after consent and registration approval. A campaign confirmation text field is not an automatic sender. If no suitable manual facility is available, leave daily delivery disabled and ask for a separately implemented confirmation path; do not claim this procedure is operational.

Proposed manual confirmation body:

```text
Scotland Facts by Elumsden Sole: You agreed to automated Scotland facts, up to 1 fact/day plus enrollment and requested service replies. Message and data rates may apply. Reply STOP to opt out. Reply HELP for help or email brunslx@gmail.com.
```

The no-URL restriction applies to application-generated daily facts, not this manually controlled service message. This template is under 300 characters and contains program name, enrollment acknowledgement, frequency, rates, STOP, HELP, and support.

1. Keep daily sending disabled. Confirm current affirmative consent and privately verify sender/recipient. Do not send while registration is rejected or pending, or while a provider block remains. Obtain explicit owner authorization for this real, potentially billable message; this task is not that authorization.
2. In the restricted consent log, create a unique enrollment-event record with disclosure version, consent evidence, exact approved confirmation body, and a confirmation state initially `NOT_ATTEMPTED`. Only one operator may handle it; no concurrent tab or second sending tool.
3. Before clicking send in the supported provider facility, persist `ATTEMPTED` and the timestamp in that private record. Recheck that no prior attempt or provider-generated confirmation exists for the event. If one exists, do not send another.
4. Make one manual send attempt. Record the returned provider Message SID and status privately. If the interface times out, crashes, or gives an unclear result, leave `ATTEMPTED`; do not click again or send a replacement. Inspect provider logs privately. If acceptance cannot be determined, keep delivery paused and contact Twilio support.
5. Record actual delivery evidence where available. A SID is not proof of handset delivery. Complete confirmation and the owner setup checklist before enabling daily messages. Never reset the attempt record to retry; a missed confirmation is safer than a duplicate and requires provider investigation.

This is an operator procedure, not an application-enforced or exactly-once guarantee. The daily application's existing commit-before-create and no-retry boundary is unchanged.

## 5. Match STOP, START, And HELP

The app sends with a `from_` number, not a configured Messaging Service SID, and has no inbound webhook. Do not assume service-level Advanced Opt-Out settings apply to this API path. Verify applicability for the actual sender type, sender-pool membership, and from-number sends with Twilio's current documentation/support. Some native or carrier responses are mandatory and not editable.

Where customization is supported and applies to this sender, proposed responses are:

```text
Scotland Facts: You are opted out. No more program messages will be sent. START may unblock the provider, but fresh consent and operator renewal are required to resume.
```

```text
Scotland Facts: The provider block may be removed. Daily facts remain paused until fresh consent and manual operator renewal. Help: brunslx@gmail.com.
```

```text
Scotland Facts by Elumsden Sole. Help: brunslx@gmail.com. Up to 1 fact/day plus enrollment and requested service replies. Message and data rates may apply. Reply STOP to opt out.
```

Do not overwrite mandatory provider language or promise these exact replies before verifying support. If native STOP says START resubscribes and cannot be changed, retain it and disclose in the campaign flow, terms, and enrollment script that this only clears the provider block: the application still needs fresh consent and manual renewal. If HELP cannot be customized to include contact information on this sender, resolve a supported configuration with Twilio before resubmission. Do not merely paste a desired HELP message into registration and assume it runs.

The owner must monitor Twilio incoming messages and brunslx@gmail.com before every daily send. STOP or a direct opt-out requires disabling local/hosted gates, persisting `subscription suppress`, and removing recipient configuration as detailed in `USER_SETUP.md`. Error `21610` suppression is a fallback, not an inbound listener. START never clears application suppression automatically.

Only perform actual SMS keyword/confirmation tests with explicit owner authorization, applicable registration approval, and a consenting test recipient. Keep a private record of the actual native responses and resulting provider block/application suppression; do not attach unredacted screenshots to the public repository. If monitoring or provider behavior cannot be verified, do not enable daily sending.

## 6. Resubmit And Wait

After the above is true, the owner can update the rejected submission with the verified distinct URLs, truthful verbal flow, exact applicable keyword responses, confirmation procedure, and daily samples. Provide the public script as opt-in evidence; submit any requested private consent evidence only through an authorized private provider channel, not GitHub Pages or Issues. Review screenshots for personal data before sharing them.

Wait for Twilio/carrier approval. Then complete migration `002`, deployed RLS/API access checks, persisted dry-run validation, current consent, confirmation handling, and explicit production authorization in `USER_SETUP.md`. This local update does not certify external accounts, deployed security, consent, approval, delivery, or the published site.
