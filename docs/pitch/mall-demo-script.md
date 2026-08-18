# Mall Pitch — Demo Script & Talk Track

*Cold first meeting. Room is likely: Mall GM or Operations Head, Security Head, and possibly one IT person. 30–40 minutes. Objective: leave with a named zone and a pilot date.*

---

## Before you walk in

**Set up, in this order:**

1. Laptop with `./start.sh` running, or the hosted dashboard logged in as a demo org that has **real events in it** — a demo with an empty events feed kills the meeting.
2. Seed the demo org so the events list looks like a mall: name the site "Demo Mall", name cameras `L1 Atrium`, `L2 Corridor West`, `B1 Parking Ramp`, `Service Corridor F`, `Loading Bay`. Camera names are the single cheapest thing that makes the product feel built for them.
3. Have the **deck** open in one tab and the **dashboard** in another. Not more.
4. Phone out, on the table, WhatsApp open — you will send yourself a live alert.
5. Print two copies of the one-pager. Leave them on the table at the start, not at the end.

**Have ready but do not open unless asked:** the technical proposal. It is the follow-up email, not the meeting.

**Kill switch:** if the internet in their conference room is bad, the demo dies. Have a screen recording of the same four moments on the laptop as a fallback, and say plainly "the network here is not cooperating, here's the same thing recorded" — do not fight it live for four minutes.

---

## The arc

| # | Beat | Time | You are trying to |
|---|------|------|-------------------|
| 1 | The wall | 3 min | Get them to say the problem out loud themselves |
| 2 | The box | 3 min | Kill the "rip and replace" fear immediately |
| 3 | Live demo | 12 min | Make it concrete and make their phone buzz |
| 4 | Security | 5 min | Let the IT person mark it safe, in front of the GM |
| 5 | The ask | 5 min | Get a zone named and a date |
| — | Q&A | rest | |

---

## 1 — The wall (3 min)

**Do not open the laptop yet.** Open with a question, not a slide.

> "Before I show you anything — how many cameras are on the estate right now?"

Whatever number they say, write it down visibly. Then:

> "And in the control room on a given shift, how many people are watching?"

Let the ratio sit for a second without commenting on it. Then say the one thing that reframes it:

> "I'm not here to tell you your team isn't watching properly. I'm here because nobody can. Watching a wall of static feeds is a task where human attention measurably falls off after about twenty minutes — that's the task, not the people. So your CCTV ends up being something you search after a complaint, rather than something that tells you anything while it's happening."

**Then** open the deck at slide 2 and let the video-wall graphic land for a beat.

**The line to land:** *"The footage was never the problem. The reviewing was."*

> ⚠️ **Do not** say "AI" yet. Not once. It arrives in beat 3 as an explanation of something they've already seen work.

---

## 2 — The box (3 min)

Their unspoken fear is a six-figure rip-and-replace and a three-month project. Kill it in the first sentence.

> "Nothing gets ripped out. Your cameras, your cabling, your NVR, your recording policy — all unchanged. We add one box to the control room that reads the streams you're already recording. Half a day to install. If you hate it, we unplug it and you're exactly where you started."

Deck slide 5 — the architecture line. Trace it with your finger, left to right, and say the sentence that matters most to the room:

> "The video stays in the building. What leaves is an event — a description, a snapshot, a ten-second clip. We are not shipping your mall's footage anywhere."

Pause there. This is where the IT person's shoulders drop.

---

## 3 — Live demo (12 min)

Switch to the dashboard. **Four moments, in this order.** Resist showing anything else — every extra screen dilutes the four that work.

### Moment A — The events feed (2 min)

Land on the events list. Do not narrate the UI. Read one event out loud as if you were the duty manager:

> "22:41, Service Corridor F, one person, six minutes after that unit shut. Here's the snapshot, here's the clip."

Then:

> "That's the whole product, really. Everything else is how you tune what shows up here and who gets told."

### Moment B — Draw a zone, in front of them (3 min)

Open a camera, open the zone editor, and **draw a polygon live** while talking.

> "Say this corner is the high-value line. I draw it, and I say: after closing, any person in this shape is an event. That's it — that's the configuration."

**Why this beat matters:** it converts "AI product" into "a thing my security head can operate." Drawing it badly and fixing it is *better* than a smooth pre-made zone — it proves it's editable.

Hand the trackpad to the Security Head and ask them to draw one. If they take it, you have effectively won the meeting.

### Moment C — Describe a rule in English (4 min)

**This is your differentiator. Give it the most time.**

Open the sequence chat and type something *they* just told you they care about. If earlier they mentioned shutters, type shutters. If they mentioned the parking ramp, type that.

> "Tell me if someone is at the till for more than three minutes with no staff around, and message the floor manager."

Let it ask its clarifying question on screen. Point at it:

> "Notice it asked rather than guessed. And notice nothing is live yet — it's drafted a rule, and a person has to press save. It proposes; your team decides. We deliberately don't let it switch things on by itself."

Save it. Then:

> "Your security head writes rules in the words they'd use on the radio. Nobody has to learn our menu."

### Moment D — Make a phone buzz (3 min)

Trigger an event — walk in front of the demo camera, or replay a clip into it. Wait for the WhatsApp to arrive on the phone on the table.

> "That's the duty manager's phone. No app to install, no password to remember at 2 a.m. It's WhatsApp."

Then close the demo on the digest:

> "And at 7 a.m. your security head gets a paragraph covering the whole night, instead of opening a system."

> ⚠️ **Do not demo:** live video wall (one camera at a time only), footfall analytics (doesn't exist), fall detection (not validated), cross-camera tracking (not built). If asked, answer from the roadmap honestly — see objections below.

---

## 4 — Security (5 min)

Turn to the IT person directly, by name, and go through deck slide 10 briskly. Six answers, one line each:

- Continuous video never leaves the premises
- Outbound connections only — no port forwarding, no VPN into your LAN, no inbound rule
- No permanent cloud keys on the box; it gets short-lived credentials you can revoke instantly
- **No facial recognition** — we detect people and behaviour, we don't identify anyone
- Your data is scoped to your organisation and enforced on every query
- Everything is logged: who looked at which camera, who changed which rule

Then hand them the technical proposal link:

> "There's a full technical document with the port list, the exact data inventory, and the failure modes. I'll send it today — I'd rather your team pick holes in it before we install than after."

**Offering the document unprompted is the move.** It signals you expect scrutiny.

---

## 5 — The ask (5 min)

Deck slide 11, then the closing question — and then **stop talking**:

> "Twelve cameras, one zone, thirty days. We install in half a day, you set the pass mark before we start, and if it doesn't clear it we take the box back and you've lost a day.
>
> So — which zone worries you most?"

Silence. Let them answer. The zone they name is the pilot.

**Then nail down three things before you leave the room:**

1. **The zone** — write it down and read it back
2. **A named person** from their security team
3. **A date for the pre-install check** — not the install, just the 20-minute call to get the NVR model. It is a small ask, which is why it gets a yes.

Ask for the NVR make and model before you leave. It is the single most common install-day surprise, and asking makes you look like you've done this.

---

## Objection handling

| They say | You say |
|---|---|
| **"We already have AI in our NVR."** | "Most NVR analytics are line-crossing and motion zones — they fire on rain and shadows, and I'd guess your team has switched half of them off. Ask them. The difference is ours describes *what* happened in a sentence, and lets you write the rule in English. Test it against theirs on the same twelve cameras for thirty days." |
| **"How much?"** *(early)* | "Two parts — the boxes and a per-camera monthly. But I'm not going to quote your estate before the pilot, because the number of cameras one box covers depends on your streams, and I'd be making it up. The pilot measures it. Let's price the real thing." |
| **"Can it catch shoplifting?"** | "It can catch the *behaviours* around it — someone in a zone too long, someone in a staff-only corridor, movement at a shutter after close. It cannot tell you an item was concealed, and anyone who tells you their system does that is overselling. What it does is put the moment in front of a human in seconds instead of two hours." |
| **"Can it track a person across cameras?"** | "Not today. It's on the roadmap, and when it comes it'll be based on which cameras you tell us are physically adjacent plus timing — not facial recognition. We're deliberately not building a face database." |
| **"Does it do face recognition / can we match a watchlist?"** | "No, and that's a deliberate decision, not a gap. It's the fastest way to turn a security tool into a compliance problem. We detect people and behaviour, not identities." |
| **"What about false alarms? We turned off the last system."** | "You should expect week one to be noisy — I'd rather say that now than have you find out. The honest question isn't the day-one rate, it's whether tuning brings it down and keeps it down. That's what weeks one to four of the pilot are for, and it's the number I'd want you to judge us on." |
| **"Our internet is unreliable."** | "Detection runs on the box, so it keeps working. Events queue locally and deliver when the link comes back. You get delayed alerts, not missing ones. And there's no video uplink at all — an event is a couple of megabytes." |
| **"Can our tenants get access to their own shop's camera?"** | "Not yet — accounts are scoped to the whole site today. Per-zone restriction is on the roadmap and it's specifically on there because of estates like yours. I'll flag it honestly in the document." |
| **"Who's responsible if something is missed?"** | "We surface events; your team decides and acts. We're not a monitoring service and we don't take on guarding liability. Your NVR stays the system of record for anything evidentiary." |
| **"Send us a proposal and we'll get back to you."** | "I will — today. Can I also put twenty minutes in the diary next week just to get your NVR model and confirm a read-only account is possible? Whether or not you proceed, that's the thing that decides if a pilot is even straightforward here." |

---

## After the meeting — same day

1. Send the **one-pager link** and the **technical proposal link** in one short email.
2. Restate the zone they named, the person they nominated, and the date, in three bullets.
3. Attach the pre-install information request: NVR make and model, concurrent stream limit, read-only account confirmation, and the twelve cameras in the named zone.

Do not attach the deck. The deck was the meeting; the one-pager is what gets forwarded.
