"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Landing page.
 *
 * Direction: the page is a night shift. The hero is not a headline over a
 * gradient — it is a working monitor wall, drawn rather than photographed,
 * with the agent walking across it one camera at a time and saying what it
 * sees. Everything else on the page is quiet so that wall is the one thing
 * you remember.
 *
 * The tiles are rendered in CSS, not stock footage. Fake "camera feeds" made
 * from stock photos read as fake, and the product's own VMS look is more
 * ours than a photo of somebody else's building.
 *
 * Sodium amber (#E8A33D) is the colour of a car park at 2am and is reserved
 * for the machine's own output — detections, readings, proposals. Brand blue
 * is for things a person clicks. Do not mix the two.
 */

const GROUND = "#07080A";
const PANEL = "#0F1116";
const LINE = "#22262E";
const INK = "#EDEFF2";
const MUTED = "#868D97";
const DIM = "#5A606A";
const BRAND = "#1E90FF";
const SODIUM = "#E8A33D";

type Cam = {
  id: string;
  place: string;
  /** Where the light falls in the tile, as a CSS position. */
  light: string;
  /** Detection box, in % of the tile. */
  box: { x: number; y: number; w: number; h: number };
  /** What is standing in the box — drawn as a silhouette. */
  shape: "person" | "pair" | "vehicle" | "door";
  label: string;
  read: string;
};

const CAMS: Cam[] = [
  {
    id: "CAM-03",
    place: "Service corridor",
    light: "62% 78%",
    box: { x: 54, y: 52, w: 20, h: 34 },
    shape: "person",
    label: "person · 0.94",
    read: "Person in the service corridor, stopped at the roller shutter. Nobody rostered here until 06:00.",
  },
  {
    id: "CAM-07",
    place: "Loading bay",
    light: "30% 65%",
    box: { x: 20, y: 44, w: 26, h: 30 },
    shape: "vehicle",
    label: "vehicle · 0.88",
    read: "Van reversed to bay 2 and has been stationary with the engine running for four minutes.",
  },
  {
    id: "CAM-11",
    place: "Atrium north",
    light: "50% 40%",
    box: { x: 42, y: 30, w: 16, h: 26 },
    shape: "person",
    label: "person · 0.91",
    read: "One person crossing the atrium toward the north stair. Normal for this hour.",
  },
  {
    id: "CAM-14",
    place: "Till line",
    light: "72% 55%",
    box: { x: 60, y: 36, w: 22, h: 32 },
    shape: "pair",
    label: "person ×2 · 0.90",
    read: "Two people behind the till line after close. The tills were locked at 21:40.",
  },
  {
    id: "CAM-18",
    place: "Car park level 2",
    light: "38% 30%",
    box: { x: 28, y: 22, w: 24, h: 28 },
    shape: "person",
    label: "person · 0.86",
    read: "Someone walking the parked rows, third pass in eleven minutes.",
  },
  {
    id: "CAM-22",
    place: "Fire exit east",
    light: "55% 68%",
    box: { x: 48, y: 56, w: 18, h: 30 },
    shape: "door",
    label: "door held · 0.97",
    read: "Fire exit propped open. Nothing has come through it yet.",
  },
];

export default function LandingPage() {
  return (
    <div style={{ background: GROUND, color: INK }} className="nw min-h-screen font-sans">
      <Styles />
      <Nav />
      <main>
        <Hero />
        <Kit />
        <Boundary />
        <SetsItselfUp />
        <Gets />
        <Close />
      </main>
      <Footer />
    </div>
  );
}

/* ------------------------------------------------------------------ hooks */

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const set = () => setReduced(mq.matches);
    set();
    mq.addEventListener("change", set);
    return () => mq.removeEventListener("change", set);
  }, []);
  return reduced;
}

/** True once the element has been on screen. Used for scroll reveals. */
function useInView<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting) {
          setSeen(true);
          io.disconnect();
        }
      },
      { rootMargin: "-10% 0px -10% 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return { ref, seen };
}

function Reveal({
  children,
  delay = 0,
  as: Tag = "div",
  className = "",
}: {
  children: React.ReactNode;
  delay?: number;
  as?: React.ElementType;
  className?: string;
}) {
  const { ref, seen } = useInView<HTMLDivElement>();
  return (
    <Tag
      ref={ref}
      className={`nw-reveal ${seen ? "is-in" : ""} ${className}`}
      style={{ transitionDelay: `${delay}ms` }}
    >
      {children}
    </Tag>
  );
}

/* -------------------------------------------------------------------- nav */

function Nav() {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <nav
      className="fixed inset-x-0 top-0 z-50 transition-all duration-300"
      style={{
        background: scrolled ? `${GROUND}e6` : "transparent",
        backdropFilter: scrolled ? "blur(12px)" : "none",
        borderBottom: `1px solid ${scrolled ? LINE : "transparent"}`,
      }}
    >
      <div
        className="mx-auto flex max-w-6xl items-center justify-between px-6 transition-all duration-300"
        style={{ height: scrolled ? 60 : 76 }}
      >
        <span className="font-mono text-sm tracking-[0.22em]">NIGHTWATCH</span>
        <div className="flex items-center gap-5">
          <Link href="/login" className="nw-link text-sm" style={{ color: MUTED }}>
            Sign in
          </Link>
          <Link href="/login" className="nw-btn nw-btn-primary text-sm">
            Book a pilot
          </Link>
        </div>
      </div>
    </nav>
  );
}

/* ------------------------------------------------------------------- hero */

function Hero() {
  return (
    <section className="relative overflow-hidden px-6 pb-16 pt-28 sm:pt-36">
      <div className="nw-glow" aria-hidden="true" />
      <div className="mx-auto max-w-6xl">
        <div className="nw-enter" style={{ animationDelay: "40ms" }}>
          <span className="font-mono text-[11px] tracking-[0.2em]" style={{ color: DIM }}>
            CCTV EVENT INTELLIGENCE
          </span>
        </div>

        <h1
          className="nw-enter mt-5 max-w-3xl font-heading text-[2.6rem] font-bold leading-[1.03] tracking-[-0.035em] sm:text-[4rem]"
          style={{ animationDelay: "120ms", textWrap: "balance" }}
        >
          Your cameras already saw it.
          <br />
          <span style={{ color: DIM }}>Nobody was watching.</span>
        </h1>

        <p
          className="nw-enter mt-6 max-w-xl text-[15px] leading-relaxed"
          style={{ animationDelay: "200ms", color: MUTED }}
        >
          A wall of feeds is not coverage. Nightwatch puts a small box on your
          network that watches every camera you already own, and tells your team
          what happened while there is still time to act.
        </p>

        <div className="nw-enter mt-8 flex flex-wrap items-center gap-3" style={{ animationDelay: "280ms" }}>
          <Link href="/login" className="nw-btn nw-btn-primary text-sm">
            Book a pilot <ArrowRight className="h-4 w-4" />
          </Link>
          <a href="#boundary" className="nw-btn nw-btn-ghost text-sm">
            What leaves the building
          </a>
        </div>

        <div id="wall" className="nw-enter mt-14" style={{ animationDelay: "360ms" }}>
          <LiveWall />
        </div>
      </div>
    </section>
  );
}

/**
 * The signature. Six tiles, and the agent walking across them: brackets snap
 * onto the camera it is reading, a detection box lands, and its sentence
 * types out underneath in its own colour. This is the product's actual claim,
 * demonstrated rather than described.
 */
function LiveWall() {
  const reduced = usePrefersReducedMotion();
  const { ref, seen } = useInView<HTMLDivElement>();
  const [active, setActive] = useState(0);
  const [typed, setTyped] = useState(reduced ? CAMS[0].read : "");
  const [clock, setClock] = useState("02:47:04");

  // Advance to the next camera. Held still for anyone who asked for less motion.
  useEffect(() => {
    if (reduced || !seen) return;
    const t = setInterval(() => setActive((i) => (i + 1) % CAMS.length), 4200);
    return () => clearInterval(t);
  }, [reduced, seen]);

  // Type the reading out. Instant when motion is reduced.
  useEffect(() => {
    const full = CAMS[active].read;
    if (reduced) {
      setTyped(full);
      return;
    }
    setTyped("");
    let i = 0;
    const t = setInterval(() => {
      i += 2;
      setTyped(full.slice(0, i));
      if (i >= full.length) clearInterval(t);
    }, 16);
    return () => clearInterval(t);
  }, [active, reduced]);

  // Burn-in timecode. Seeded to a fixed string so server and client agree,
  // then ticks on the client only.
  useEffect(() => {
    if (reduced) return;
    let s = 4;
    const t = setInterval(() => {
      s += 1;
      const mm = String(47 + Math.floor(s / 60)).padStart(2, "0");
      setClock(`02:${mm}:${String(s % 60).padStart(2, "0")}`);
    }, 1000);
    return () => clearInterval(t);
  }, [reduced]);

  const cam = CAMS[active];

  return (
    <div ref={ref} className="rounded-2xl border p-3 sm:p-4" style={{ borderColor: LINE, background: PANEL }}>
      <div className="mb-3 flex items-center justify-between px-1">
        <div className="flex items-center gap-2">
          <span className="nw-dot" />
          <span className="whitespace-nowrap font-mono text-[10px] tracking-[0.14em] sm:text-[11px]" style={{ color: MUTED }}>
            NIGHT SHIFT · 6 CAMERAS
          </span>
        </div>
        <span className="whitespace-nowrap font-mono text-[10px] sm:text-[11px]" style={{ color: DIM }}>
          {clock}
          <span className="hidden sm:inline"> · sample wall</span>
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:gap-3 md:grid-cols-3">
        {CAMS.map((c, i) => (
          <button
            key={c.id}
            type="button"
            onClick={() => setActive(i)}
            aria-label={`Show the agent's reading for ${c.place}`}
            aria-pressed={i === active}
            className="nw-tile"
            data-active={i === active ? "true" : undefined}
          >
            <span className="nw-scene" style={{ ["--light" as string]: c.light }} />
            <span className="nw-floor" />
            <span className="nw-horizon" />
            <span className="nw-grain" />
            <span className="nw-sweep" />

            <span
              className="nw-subject"
              data-shape={c.shape}
              style={{ left: `${c.box.x}%`, top: `${c.box.y}%`, width: `${c.box.w}%`, height: `${c.box.h}%` }}
            >
              {c.shape === "pair" && <span className="nw-twin" />}
              <span className="nw-box">
                <span className="nw-box-tag">{c.label}</span>
              </span>
            </span>

            <span className="nw-bracket nw-bl" />
            <span className="nw-bracket nw-br" />

            <span className="nw-tile-id">{c.id}</span>
            <span className="nw-tile-place">{c.place}</span>
          </button>
        ))}
      </div>

      <div className="mt-3 rounded-lg border p-4" style={{ borderColor: LINE, background: GROUND }}>
        <div className="flex items-baseline justify-between gap-4">
          <span className="font-mono text-[11px] tracking-[0.14em]" style={{ color: SODIUM }}>
            AGENT READING · {cam.id}
          </span>
          <span className="hidden font-mono text-[11px] sm:block" style={{ color: DIM }}>
            {cam.place}
          </span>
        </div>
        <p className="mt-2 min-h-[3rem] font-mono text-[13px] leading-6 sm:min-h-[1.5rem]" style={{ color: SODIUM }}>
          {typed}
          <span className="nw-caret" aria-hidden="true" />
        </p>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------- kit strip */

const BRANDS = ["CP PLUS", "HIKVISION", "DAHUA", "UNIVIEW", "AXIS", "TP-LINK VIGI", "ANY RTSP NVR"];

function Kit() {
  return (
    <section className="overflow-hidden border-y py-4" style={{ borderColor: LINE }}>
      <div className="nw-marquee">
        <div className="nw-marquee-track">
          {[0, 1].map((copy) => (
            <div key={copy} className="flex shrink-0 items-center" aria-hidden={copy === 1}>
              {BRANDS.map((b) => (
                <span key={b} className="flex items-center gap-8 px-8 font-mono text-[11px] tracking-[0.18em]" style={{ color: DIM }}>
                  {b}
                  <span className="h-1 w-1 rounded-full" style={{ background: LINE }} />
                </span>
              ))}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* --------------------------------------------------------------- boundary */

function Boundary() {
  const { ref, seen } = useInView<HTMLDivElement>();

  return (
    <section id="boundary" className="px-6 py-24">
      <div className="mx-auto max-w-6xl">
        <Reveal>
          <h2 className="font-heading text-3xl font-bold tracking-[-0.025em] sm:text-4xl">
            The video stays in your building.
          </h2>
          <p className="mt-3 max-w-xl text-[15px] leading-relaxed" style={{ color: MUTED }}>
            Detection runs on the box, not in our cloud. That is not a setting —
            there is no continuous video uplink to turn on.
          </p>
        </Reveal>

        {/* The argument, drawn: video loops inside the premises and stops dead
            at the boundary; only small event payloads travel the wire. */}
        <div ref={ref} className={`nw-reveal mt-10 ${seen ? "is-in" : ""}`}>
          <div className="grid items-stretch gap-3 rounded-2xl border p-3 sm:p-5 md:grid-cols-[1fr_auto_1fr]" style={{ borderColor: LINE, background: PANEL }}>
            <div className="rounded-xl border p-5" style={{ borderColor: LINE, background: GROUND }}>
              <div className="font-mono text-[11px] tracking-[0.14em]" style={{ color: MUTED }}>
                YOUR PREMISES
              </div>
              <div className="mt-4 space-y-2">
                <span className="nw-stream" />
                <span className="nw-stream" style={{ animationDelay: "-1.1s" }} />
                <span className="nw-stream" style={{ animationDelay: "-2.3s" }} />
              </div>
              <p className="mt-4 text-[13px] leading-relaxed" style={{ color: MUTED }}>
                Every camera, continuously. Analysed on the box, then discarded.
                Credentials never leave the LAN.
              </p>
            </div>

            <div className="nw-wire" aria-hidden="true">
              <span className="nw-stop" />
              <span className="nw-edge" />
              <span className="nw-wire-line" />
              <span className="nw-packet" />
              <span className="nw-packet" style={{ animationDelay: "-1.6s" }} />
              <span className="nw-packet" style={{ animationDelay: "-3.2s" }} />
              <span className="nw-wire-label">events only</span>
            </div>

            <div className="rounded-xl border p-5" style={{ borderColor: LINE, background: GROUND }}>
              <div className="font-mono text-[11px] tracking-[0.14em]" style={{ color: MUTED }}>
                WHAT WE RECEIVE
              </div>
              <ul className="mt-4 space-y-2.5">
                {[
                  ["A description", "one sentence saying what was seen"],
                  ["One snapshot", "the moment, annotated"],
                  ["A 10-second clip", "five seconds either side"],
                ].map(([t, d]) => (
                  <li key={t} className="flex gap-3">
                    <span className="mt-2 h-1 w-1 shrink-0 rounded-full" style={{ background: SODIUM }} />
                    <span className="text-sm">
                      {t}
                      <span className="block text-[13px]" style={{ color: MUTED }}>
                        {d}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>

        <Reveal delay={80}>
          <p className="mt-5 font-mono text-xs" style={{ color: DIM }}>
            No inbound firewall rule. No port forwarding. No VPN into your network.
          </p>
        </Reveal>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ setup */

const STEPS: [string, string][] = [
  ["Pick a batch", "Select the cameras you want set up. A floor, a wing, whatever you think of as one place."],
  ["It watches them", "Each box samples its own cameras for a few minutes. Frames go from the box straight to the model — never through us."],
  ["It proposes", "One configuration per camera, grouped by scene, each with a plain-English reason for what it turned on and what it left off."],
  ["You approve", "Nothing takes effect until a person says so. Approve a group of twelve, or take one camera on its own."],
];

/**
 * Auto-advancing because setup genuinely is an ordered process — the step
 * numbers carry information, and walking them is the shortest way to show
 * that approval sits at the end rather than the start.
 */
function SetsItselfUp() {
  const reduced = usePrefersReducedMotion();
  const { ref, seen } = useInView<HTMLDivElement>();
  const [step, setStep] = useState(0);
  const [held, setHeld] = useState(false);

  useEffect(() => {
    if (reduced || !seen || held) return;
    const t = setInterval(() => setStep((s) => (s + 1) % STEPS.length), 4500);
    return () => clearInterval(t);
  }, [reduced, seen, held]);

  const pick = useCallback((i: number) => {
    setStep(i);
    setHeld(true);
  }, []);

  return (
    <section id="setup" className="px-6 py-24" style={{ background: PANEL }}>
      <div className="mx-auto max-w-6xl">
        <Reveal>
          <h2 className="font-heading text-3xl font-bold tracking-[-0.025em] sm:text-4xl">It sets itself up.</h2>
          <p className="mt-3 max-w-xl text-[15px] leading-relaxed" style={{ color: MUTED }}>
            Four hundred cameras is four hundred rounds of the same judgement,
            made by someone who is not a computer-vision engineer. So the agent
            does the first pass and shows its working.
          </p>
        </Reveal>

        <div ref={ref} className="mt-10 grid gap-px overflow-hidden rounded-2xl border md:grid-cols-4" style={{ borderColor: LINE, background: LINE }}>
          {STEPS.map(([title, body], i) => (
            <button
              key={title}
              type="button"
              onClick={() => pick(i)}
              aria-pressed={i === step}
              className="nw-step"
              data-active={i === step ? "true" : undefined}
            >
              <span className="nw-step-bar">
                <span className="nw-step-fill" />
              </span>
              <span className="nw-step-n">{String(i + 1).padStart(2, "0")}</span>
              <span className="nw-step-t">{title}</span>
              <span className="nw-step-b">{body}</span>
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}

/* --------------------------------------------------------------- what you get */

const GETS: [string, string][] = [
  ["Zones and rules per area", "A corridor at 3am and an atrium at 3pm are not the same problem."],
  ["Rules in plain English", "Describe what you want watched. It asks a question if it needs one, then drafts the rule."],
  ["Ask the record", "“Anything near the food court between 9 and 11?” — answered from events, with the clips."],
  ["Alerts that escalate", "Duty manager, then security head, then the GM, until somebody acknowledges."],
  ["A morning recap", "What happened overnight, in a paragraph, before your security lead arrives."],
  ["No facial recognition", "We detect people and behaviour in a zone. We do not identify anyone. That is a decision, not a gap."],
];

function Gets() {
  return (
    <section id="gets" className="px-6 py-24">
      <div className="mx-auto max-w-6xl">
        <Reveal>
          <h2 className="font-heading text-3xl font-bold tracking-[-0.025em] sm:text-4xl">
            What your team actually gets.
          </h2>
        </Reveal>

        <dl className="mt-8 grid gap-x-10 sm:grid-cols-2">
          {GETS.map(([t, d], i) => (
            <Reveal key={t} as="div" delay={(i % 2) * 60 + Math.floor(i / 2) * 40}>
              <div className="nw-get border-t py-5" style={{ borderColor: LINE }}>
                <dt className="text-sm font-medium">{t}</dt>
                <dd className="mt-1 text-[13px] leading-relaxed" style={{ color: MUTED }}>
                  {d}
                </dd>
              </div>
            </Reveal>
          ))}
        </dl>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------- close */

function Close() {
  return (
    <section className="px-6 pb-24">
      <Reveal>
        <div className="relative isolate mx-auto max-w-6xl overflow-hidden rounded-2xl border" style={{ borderColor: LINE }}>
          {/* Unsplash, free licence, commercial use permitted. */}
          <img
            src="https://images.unsplash.com/photo-1557597774-9d273605dfa9?auto=format&fit=crop&w=1600&q=70"
            alt=""
            aria-hidden="true"
            className="absolute inset-0 -z-10 h-full w-full object-cover opacity-[0.18] grayscale"
            loading="lazy"
          />
          <div className="absolute inset-0 -z-10" style={{ background: `linear-gradient(90deg, ${GROUND}f5, ${GROUND}b0)` }} />

          <div className="px-8 py-16 sm:px-12 sm:py-24">
            <h2 className="max-w-lg font-heading text-3xl font-bold leading-tight tracking-[-0.025em] sm:text-4xl">
              Which zone worries you most?
            </h2>
            <p className="mt-3 max-w-md text-[15px]" style={{ color: MUTED }}>
              Start there. Twelve cameras, thirty days, and a pass mark you set
              before we begin.
            </p>
            <div className="mt-8">
              <Link href="/login" className="nw-btn nw-btn-primary text-sm">
                Book a pilot <ArrowRight className="h-4 w-4" />
              </Link>
            </div>
          </div>
        </div>
      </Reveal>
    </section>
  );
}

/**
 * Footer. Structured like a proper site footer — brand statement, a row of
 * commitments where a competitor would put certification badges, then link
 * columns and a legal line.
 *
 * The commitments are the three claims the page above actually substantiates.
 * They sit here instead of award badges because we have no awards to show and
 * a footer is the last place to start implying otherwise.
 *
 * Every link resolves: sections on this page, or routes that exist. Add a
 * column here only when there is somewhere real for it to point.
 */

const COMMITMENTS: [string, string][] = [
  ["Video stays on-site", "analysed on the box, then discarded"],
  ["No facial recognition", "behaviour in a zone, never identity"],
  ["No inbound ports", "outbound connection only, no VPN"],
];

const FOOTER_LINKS: [string, [string, string][]][] = [
  [
    "The product",
    [
      ["What it watches", "#wall"],
      ["What leaves the building", "#boundary"],
      ["How it sets itself up", "#setup"],
      ["What your team gets", "#gets"],
    ],
  ],
  [
    "Get started",
    [
      ["Book a pilot", "/login"],
      ["Sign in", "/login"],
      ["Connect a device", "/cameras/connect"],
    ],
  ],
];

function Footer() {
  return (
    <footer className="border-t px-6 pb-10 pt-16" style={{ borderColor: LINE, background: PANEL }}>
      <div className="mx-auto max-w-6xl">
        <div className="grid gap-12 lg:grid-cols-[1.1fr_1fr]">
          <div>
            <span className="font-mono text-xl tracking-[0.24em]" style={{ color: INK }}>
              NIGHTWATCH
            </span>
            <p className="mt-5 max-w-sm text-[15px] leading-relaxed" style={{ color: MUTED }}>
              Nightwatch watches the cameras you already own and tells your team
              what happened, from a box that sits on your own network.
            </p>
          </div>

          <div className="grid gap-8 sm:grid-cols-3">
            {FOOTER_LINKS.map(([heading, links]) => (
              <div key={heading}>
                <h3 className="font-mono text-[11px] tracking-[0.16em]" style={{ color: DIM }}>
                  {heading.toUpperCase()}
                </h3>
                <ul className="mt-4 space-y-2.5">
                  {links.map(([label, href]) => (
                    <li key={label + href}>
                      {href.startsWith("#") ? (
                        <a href={href} className="nw-link text-sm" style={{ color: MUTED }}>
                          {label}
                        </a>
                      ) : (
                        <Link href={href} className="nw-link text-sm" style={{ color: MUTED }}>
                          {label}
                        </Link>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}

            <div>
              <h3 className="font-mono text-[11px] tracking-[0.16em]" style={{ color: DIM }}>
                WORKS WITH
              </h3>
              <ul className="mt-4 space-y-2.5 text-sm" style={{ color: MUTED }}>
                {["CP Plus", "Hikvision", "Dahua", "Uniview", "Any RTSP NVR"].map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>

        {/* Where a competitor puts award badges. These are commitments, and
            each one is argued for further up the page. */}
        <div className="mt-14 grid gap-px overflow-hidden rounded-xl border sm:grid-cols-3" style={{ borderColor: LINE, background: LINE }}>
          {COMMITMENTS.map(([title, detail]) => (
            <div key={title} className="px-5 py-4" style={{ background: GROUND }}>
              <div className="text-sm font-medium" style={{ color: INK }}>
                {title}
              </div>
              <div className="mt-1 font-mono text-[11px]" style={{ color: DIM }}>
                {detail}
              </div>
            </div>
          ))}
        </div>

        <div
          className="mt-10 flex flex-col items-start justify-between gap-3 border-t pt-6 sm:flex-row sm:items-center"
          style={{ borderColor: LINE }}
        >
          <span className="font-mono text-[11px]" style={{ color: DIM }}>
            © {new Date().getFullYear()} Nightwatch · CCTV event intelligence
          </span>
          <Link href="/login" className="nw-link text-[13px]" style={{ color: MUTED }}>
            Sign in →
          </Link>
        </div>
      </div>
    </footer>
  );
}

/* ------------------------------------------------------------------ styles */

function Styles() {
  return (
    <style>{`
.nw ::selection { background: ${SODIUM}; color: ${GROUND}; }
/* The nav is fixed, so anchored sections need room above them. */
.nw [id] { scroll-margin-top: 90px; }

/* Buttons and links ------------------------------------------------------ */
.nw .nw-btn {
  display: inline-flex; align-items: center; gap: .5rem;
  border-radius: .5rem; padding: .7rem 1.2rem; font-weight: 500;
  transition: transform .18s ease, background-color .18s ease, border-color .18s ease, opacity .18s ease;
}
.nw .nw-btn-primary { background: ${BRAND}; color: #fff; }
.nw .nw-btn-primary:hover { transform: translateY(-1px); opacity: .92; }
.nw .nw-btn-ghost { border: 1px solid ${LINE}; color: ${MUTED}; }
.nw .nw-btn-ghost:hover { border-color: ${DIM}; color: ${INK}; }
.nw .nw-link { border-radius: 3px; transition: color .18s ease; }
.nw .nw-link:hover { color: ${INK}; }
.nw :is(.nw-btn, .nw-link, .nw-tile, .nw-step):focus-visible {
  outline: 2px solid ${BRAND}; outline-offset: 3px;
}

/* Entrance and scroll reveal --------------------------------------------- */
@keyframes nw-enter { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: none; } }
.nw .nw-enter { opacity: 0; animation: nw-enter .7s cubic-bezier(.2,.7,.3,1) forwards; }
.nw .nw-reveal { opacity: 0; transform: translateY(14px); transition: opacity .6s ease, transform .6s cubic-bezier(.2,.7,.3,1); }
.nw .nw-reveal.is-in { opacity: 1; transform: none; }

/* Hero atmosphere: one light source, high and left, like a yard lamp ----- */
.nw .nw-glow {
  position: absolute; inset: -25% 0 auto -10%; height: 640px; pointer-events: none;
  background: radial-gradient(60% 60% at 30% 0%, ${BRAND}1f, transparent 70%);
}

/* Live wall -------------------------------------------------------------- */
@keyframes nw-blink { 0%,100% { opacity: 1; } 50% { opacity: .25; } }
.nw .nw-dot { width: 6px; height: 6px; border-radius: 999px; background: ${SODIUM}; animation: nw-blink 2s ease-in-out infinite; }

.nw .nw-tile {
  position: relative; display: block; width: 100%; aspect-ratio: 16 / 10;
  overflow: hidden; border-radius: .6rem; border: 1px solid ${LINE};
  background: #0A0C10; text-align: left;
  transition: border-color .3s ease, transform .3s ease;
}
.nw .nw-tile:hover { border-color: #333944; }
.nw .nw-tile[data-active] { border-color: ${SODIUM}66; }
.nw .nw-tile[data-active] .nw-scene { filter: brightness(1.25); }
.nw .nw-scene { transition: filter .4s ease; }

/* The "scene": a pool of light on a dark floor. Cheap, but it reads as a
   room at night far better than a stock photo pretending to be a feed. */
.nw .nw-scene {
  position: absolute; inset: 0;
  background:
    radial-gradient(38% 46% at var(--light), rgba(200,215,240,.16), transparent 72%),
    linear-gradient(180deg, #0C0F14 0%, #090B0F 60%, #06070A 100%);
}
/* A floor in perspective and a horizon: two lines are enough to turn a dark
   rectangle into a room seen from a ceiling mount. */
.nw .nw-floor {
  position: absolute; left: -60%; right: -60%; bottom: -34%; height: 92%;
  transform: perspective(150px) rotateX(64deg); transform-origin: 50% 100%;
  opacity: .5;
  background-image:
    linear-gradient(90deg, rgba(160,185,220,.12) 1px, transparent 1px),
    linear-gradient(0deg, rgba(160,185,220,.10) 1px, transparent 1px);
  background-size: 26px 26px;
}
.nw .nw-horizon {
  position: absolute; left: 0; right: 0; top: 41%; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(180,205,240,.22), transparent);
}
.nw .nw-grain {
  position: absolute; inset: 0; opacity: .5;
  background-image: repeating-linear-gradient(0deg, rgba(255,255,255,.035) 0 1px, transparent 1px 3px);
}

/* Silhouettes. Drawn on every tile, not only the active one — the rooms are
   occupied whether or not the agent is currently looking at them. */
.nw .nw-subject { position: absolute; }
.nw .nw-subject::before, .nw .nw-subject::after {
  content: ""; position: absolute; background: #04050799; box-shadow: 0 0 12px #04050788;
}
/* person: body + head */
.nw .nw-subject[data-shape="person"]::before,
.nw .nw-subject[data-shape="pair"]::before {
  left: 28%; right: 28%; bottom: 0; height: 68%;
  border-radius: 44% 44% 12% 12% / 26% 26% 8% 8%;
}
.nw .nw-subject[data-shape="person"]::after,
.nw .nw-subject[data-shape="pair"]::after {
  left: 39%; width: 22%; top: 4%; height: 20%; border-radius: 999px;
}
.nw .nw-subject[data-shape="pair"] { transform: none; }
.nw .nw-subject[data-shape="pair"]::before { left: 12%; right: 44%; }
.nw .nw-subject[data-shape="pair"]::after { left: 22%; width: 18%; }
.nw .nw-subject[data-shape="pair"] .nw-twin {
  position: absolute; left: 56%; right: 8%; bottom: 0; height: 62%;
  background: #04050799; border-radius: 44% 44% 12% 12% / 26% 26% 8% 8%;
}
/* vehicle: cabin over a body */
.nw .nw-subject[data-shape="vehicle"]::before {
  left: 0; right: 0; bottom: 6%; height: 46%; border-radius: 6px 4px 4px 6px;
}
.nw .nw-subject[data-shape="vehicle"]::after {
  left: 18%; right: 26%; bottom: 46%; height: 34%; border-radius: 6px 8px 0 0;
}
/* door: an open slab with light spilling through */
.nw .nw-subject[data-shape="door"]::before {
  left: 0; width: 46%; top: 0; bottom: 0; border-radius: 2px;
}
.nw .nw-subject[data-shape="door"]::after {
  left: 46%; right: 0; top: 0; bottom: 0;
  background: linear-gradient(90deg, rgba(232,163,61,.22), transparent);
  box-shadow: none;
}
.nw .nw-sweep {
  position: absolute; inset: 0; opacity: 0;
  background: linear-gradient(180deg, transparent 0%, ${SODIUM}14 45%, ${SODIUM}22 50%, transparent 55%);
}
@keyframes nw-sweep { from { transform: translateY(-100%); } to { transform: translateY(100%); } }
.nw .nw-tile[data-active] .nw-sweep { opacity: 1; animation: nw-sweep 4.2s linear infinite; }

.nw .nw-box {
  position: absolute; inset: -6% -8%; border: 1px solid ${SODIUM}; border-radius: 2px;
  opacity: 0; transform: scale(1.08); transition: opacity .35s ease, transform .35s cubic-bezier(.2,.7,.3,1);
  box-shadow: 0 0 0 1px ${GROUND}80, 0 0 24px ${SODIUM}22;
}
.nw .nw-tile[data-active] .nw-box { opacity: 1; transform: none; transition-delay: .25s; }
.nw .nw-box-tag {
  position: absolute; left: -1px; top: -18px; padding: 1px 5px;
  background: ${SODIUM}; color: ${GROUND};
  font-family: var(--font-jetbrains-mono), ui-monospace, monospace; font-size: 9px; letter-spacing: .04em;
  white-space: nowrap; border-radius: 2px 2px 0 0;
}

/* Brackets snap on when the agent arrives at a camera. */
.nw .nw-bracket { position: absolute; width: 14px; height: 14px; opacity: 0; transition: opacity .25s ease; }
.nw .nw-bl { left: 6px; bottom: 6px; border-left: 1px solid ${SODIUM}; border-bottom: 1px solid ${SODIUM}; }
.nw .nw-br { right: 6px; bottom: 6px; border-right: 1px solid ${SODIUM}; border-bottom: 1px solid ${SODIUM}; }
.nw .nw-tile[data-active] .nw-bracket { opacity: 1; }

.nw .nw-tile-id, .nw .nw-tile-place {
  position: absolute; font-family: var(--font-jetbrains-mono), ui-monospace, monospace; font-size: 10px;
}
.nw .nw-tile-id { left: 8px; top: 7px; color: ${INK}; opacity: .8; letter-spacing: .08em; }
.nw .nw-tile-place { right: 8px; top: 7px; color: ${DIM}; }
.nw .nw-tile[data-active] .nw-tile-id { color: ${SODIUM}; opacity: 1; }

@keyframes nw-caret { 0%,100% { opacity: 1; } 50% { opacity: 0; } }
.nw .nw-caret {
  display: inline-block; width: 7px; height: 13px; margin-left: 3px;
  background: ${SODIUM}; vertical-align: -2px; animation: nw-caret 1s steps(1) infinite;
}

/* Kit marquee ------------------------------------------------------------ */
.nw .nw-marquee { position: relative; overflow: hidden; -webkit-mask-image: linear-gradient(90deg, transparent, #000 12%, #000 88%, transparent); mask-image: linear-gradient(90deg, transparent, #000 12%, #000 88%, transparent); }
@keyframes nw-marquee { from { transform: translateX(0); } to { transform: translateX(-50%); } }
.nw .nw-marquee-track { display: flex; width: max-content; animation: nw-marquee 42s linear infinite; }

/* Boundary wire ---------------------------------------------------------- */
.nw .nw-wire { position: relative; display: flex; align-items: center; justify-content: center; min-height: 72px; min-width: 96px; padding: 0 .5rem; }
.nw .nw-wire-line { position: absolute; left: 26px; right: .5rem; height: 1px; background: linear-gradient(90deg, ${SODIUM}55, ${SODIUM}55, ${LINE}); }
/* The video reaches the edge of the LAN and stops there. */
.nw .nw-stop { position: absolute; left: 0; width: 16px; height: 4px; background: ${BRAND}; border-radius: 1px; opacity: .8; }
.nw .nw-edge { position: absolute; left: 20px; top: 8px; bottom: 8px; width: 0; border-left: 1px dashed #3A4150; }
@keyframes nw-packet { 0% { left: 26px; opacity: 0; } 12% { opacity: 1; } 88% { opacity: 1; } 100% { left: 92%; opacity: 0; } }
.nw .nw-packet {
  position: absolute; top: calc(50% - 3px); width: 6px; height: 6px; border-radius: 1px;
  background: ${SODIUM}; box-shadow: 0 0 10px ${SODIUM}88; animation: nw-packet 4.8s linear infinite;
}
.nw .nw-wire-label {
  position: absolute; top: calc(50% + 14px); font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
  font-size: 10px; letter-spacing: .12em; color: ${DIM}; white-space: nowrap;
}
@media (min-width: 768px) {
  .nw .nw-wire { min-width: 132px; }
}

/* Video that never leaves: it loops in place. */
@keyframes nw-stream { from { background-position: 0 0; } to { background-position: 40px 0; } }
.nw .nw-stream {
  display: block; height: 8px; border-radius: 2px;
  background-image: repeating-linear-gradient(90deg, ${BRAND}55 0 12px, ${BRAND}18 12px 20px, ${BRAND}55 20px 40px);
  background-size: 40px 100%; animation: nw-stream 1.6s linear infinite;
}

/* Setup stepper ---------------------------------------------------------- */
.nw .nw-step {
  position: relative; display: block; text-align: left; padding: 1.6rem 1.4rem 1.5rem;
  background: ${GROUND}; transition: background-color .3s ease;
}
.nw .nw-step:hover { background: #0B0D12; }
.nw .nw-step-bar { position: absolute; inset: 0 0 auto 0; height: 2px; background: ${LINE}; }
.nw .nw-step-fill { display: block; height: 100%; width: 0; background: ${SODIUM}; }
@keyframes nw-fill { from { width: 0; } to { width: 100%; } }
.nw .nw-step[data-active] .nw-step-fill { animation: nw-fill 4.5s linear forwards; }
.nw .nw-step-n { display: block; font-family: var(--font-jetbrains-mono), ui-monospace, monospace; font-size: 11px; color: ${DIM}; transition: color .3s ease; }
.nw .nw-step[data-active] .nw-step-n { color: ${SODIUM}; }
.nw .nw-step-t { display: block; margin-top: .7rem; font-family: var(--font-space-grotesk), sans-serif; font-weight: 600; font-size: 1rem; color: ${DIM}; transition: color .3s ease; }
.nw .nw-step[data-active] .nw-step-t { color: ${INK}; }
.nw .nw-step-b { display: block; margin-top: .5rem; font-size: 13px; line-height: 1.65; color: ${MUTED}; }

/* Feature rows ----------------------------------------------------------- */
.nw .nw-get { transition: border-color .25s ease; }
.nw .nw-get:hover { border-color: ${SODIUM}55; }

/* Narrow screens: the tiles are small, so the place name gives way to the
   camera id and the detection tag shrinks with it. */
@media (max-width: 540px) {
  .nw .nw-tile-place { display: none; }
  .nw .nw-box-tag { font-size: 8px; top: -15px; }
}

/* Anyone who asked for less motion gets a still page --------------------- */
@media (prefers-reduced-motion: reduce) {
  .nw *, .nw *::before, .nw *::after {
    animation: none !important;
    transition-duration: .01ms !important;
  }
  .nw .nw-enter, .nw .nw-reveal { opacity: 1 !important; transform: none !important; }
  .nw .nw-tile[data-active] .nw-box { opacity: 1; transform: none; }
}
`}</style>
  );
}
