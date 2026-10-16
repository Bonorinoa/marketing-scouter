# Designer review: Slice 3 (2026-10-13 AM)
Verdict: **Structure PASS, card and mobile FAIL.** Nav, banner, empty state, status line, Wins strip, Work tab and the link-only guard all landed. Four P1s block calling the redesign done.

## P1
1. **Cards aren't post-first.** The bold headline is Augusto's own claim, and the post he'd be replying to isn't on the card (only an "Open post" link). The redesign's core is: the post (author, text, age) first, then why it fits, then his reply. Render the discovered post as a quoted block at the top: author handle, 2–4 lines of text, age, and an Open post link. Move the claim to the fit line ("Your angle: …"). If a card has no post text, it shouldn't be in Openings.
2. **Mobile overflows.** At 390 the header row is wider than the screen (the reply-budget pills push the page to ~496px; "7/7 LI" is cut off). Move the budget into the status line ("X: 4 of 7 left · LinkedIn: 7 of 7") and keep the tab row to tabs plus the "?" only. Assert in Playwright that document.scrollWidth <= 390.
3. **no_lens card teases a draft you can't copy** (card 1: a full draft, a grey CTA, then "No draft style for this topic yet"). See Q1.
4. **Check a post is stuck.** The error "Couldn't read that post. Paste its text." shows while the button still says "Checking…". Clear the pending state on error, put the message inline under the Text field, and focus the field. The "Where you saw it" control renders as a black X square inside a text-input-looking box with "LinkedIn" beside it. Make it two equal segments (X | LinkedIn), with the selected one filled.

## P2
5. Status line wording: "drafting works · 2 cards waiting in the queue" → "Drafts ready · 2 openings". "X was last checked just now" is good.
6. The fit line shows a slug with its hyphens swapped for spaces ("…(SCA): sca pilot ethics."). Use the topic's human label ("Matches your SCA paper: ethics of synthetic-population pilots"), and keep the slug pill only in Work.
7. Card 2's reply repeats the claim word for word, then adds a sentence. A reply should respond to the post, not restate his headline. That needs the post text from P1 fed into drafting (Systems side).
8. Full-page capture 6 shows the banner and the Showing strip floating mid-page over a card. That's probably the sticky header caught by the full-page screenshot. Check it in a real scroll. If it's real, the sticky offset is wrong.

## Answers to open questions
1. **no_lens draft:** don't show a draft you can't copy. For no_lens, show the post plus the fit line plus "No draft style for this topic yet. Reply in your own words." Make **Open post** the primary button, and keep Not for me / Later. If a draft does exist for that card, then it isn't no_lens: enable Copy.
2. **Filters:** chips, not a select. "All work" plus one chip per asset (short names), wrapping on desktop and in a single horizontally scrolling row on mobile. Add an X / LinkedIn chip pair after a divider.
3. **Later:** persist it on the server (not localStorage) for 24h. Later cards drop out of Openings into a collapsed "Saved for later (n)" row at the bottom of Today, and come back into Openings after 24h if they're still Fresh. The caps don't count them.
4. **Badges:** "Research voice" / "Civic voice" are good. Keep the colors. The Work legend line works too.
