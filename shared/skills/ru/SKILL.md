---
name: ru
description: >-
  Explain the current technical topic in Russian for a user whose default language is English, once or for the rest of the session. Use when the user asks for an explanation or an answer in Russian — "ru", "ru --full", "ru --off", "explain in Russian", "объясни по-русски", "ответь по-русски", "switch to Russian", "back to English". Not for confusion alone ("не понял" asks for a clearer answer, in English), not for a message that is simply written in Russian, and not for a quoted mention of these phrases.
---

# Explain in Russian

English stays the default. This skill changes the language of your replies to the user, never the
task, its decisions or what you are allowed to do.

## Modes

Read the flag from the user's message.

- **`ru`** (no flag) — one teaching explanation in Russian, below. The next reply is in English again,
  unless Russian mode is on.
- **`ru --full`** — Russian mode: your replies to the user in this conversation are in Russian until it
  is turned off. Confirm briefly in Russian; do not replay the last explanation. If the message also
  asks a question, answer it in Russian in the same reply.
- **`ru --off`** — Russian mode off. Confirm briefly in English and continue, also when it was not on.

Russian mode ends with `ru --off`, with a plain request such as "back to English" or "switch to
English", or with a fresh session. It does not end because the user writes in English or because a peer
agent sends a message. "Answer this one in English" changes that one reply only. Plain `ru` while
Russian mode is on gives one teaching explanation and leaves the mode on.

In Russian mode, replies are normal answers in Russian, not lessons: no glossary unless asked, and no
extra short Russian summary, since the whole reply is already in Russian.

When the conversation is summarized, keep the current state — Russian mode on or off — in the summary.
If no reliable state survives, use English.

## Teaching explanation

Choose the topic:

- With a topic or question after `ru`, explain that, even if it was not discussed before.
- Without one, explain the current unresolved topic or decision, using the last substantial answer as
  context. Do not mechanically re-explain the whole previous answer.
- If several topics fit, pick the most likely and name it in one line. If there is no usable topic,
  ask one short question.
- You only know this conversation. Do not claim to explain what another agent said in its own pane.

Write it as an explanation, not a translation:

- Start with the problem and the core idea, then develop the steps that are likely new. Skip what the
  user clearly knows; do not assume technical ignorance from difficulty with English.
- Keep the real decision, the alternatives, the trade-offs and the limits.
- Use an example from the user's own case when there is one; an analogy only when it is clearer than a
  direct example. Mark a made-up example as an example, not a project fact.

## Facts

Keep the meaning of the English discussion: claims, uncertainty, warnings, conditions, and how strong a
recommendation is. New teaching content is fine; invented project details are not. Verify a material
claim you are unsure of, as you normally would. If explaining exposes a mistake in an earlier answer,
say so plainly and correct it.

## Terms

- Code, commands, identifiers, file names, flags and error text stay exactly as they are.
- Keep a useful English technical term in English, with its Russian meaning the first time it appears:
  the user needs the English words to keep working in English. Ordinary Russian words (очередь, тест,
  ветка) are fine where they are natural.
- Add a short EN → RU glossary at the end only when several unfamiliar terms need it, or when asked.

## What stays in English

Only your replies to the user in this conversation change language. Everything that leaves the chat
stays in English: code, comments, commit messages, saved files, saved plans, docs, backlog items, PR
text, and messages to another agent. A plan written in the reply itself is part of the reply. An
explicit request for a Russian document or translation still wins.

## No side effects

Invoking `ru` only explains or changes the reply language. It does not itself edit files, write a report
or authorize implementation, and it is not a `go`. An active task stays the same task, and earlier
decisions and permissions stay as they were. Russian mode does not prevent separately authorized work:
do it normally, keeping what leaves the chat in English as above.
