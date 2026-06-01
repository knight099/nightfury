"use client";

import { useState } from "react";
import { InstallStep } from "./steps/install";
import { PairStep } from "./steps/pair";
import { DiscoverStep } from "./steps/discover";
import { TestStep } from "./steps/test";

const steps = ["Install", "Pair", "Discover", "Test"] as const;

export default function OnboardPage() {
  const [step, setStep] = useState(0);
  const [agentId, setAgentId] = useState<string | null>(null);

  return (
    <div className="min-h-screen bg-[#0D0D0D] text-[#F5F5F5]">
      <div className="max-w-2xl mx-auto p-8">
        <h1 className="text-2xl font-semibold mb-6">Connect your NVR</h1>
        <ol className="flex gap-2 mb-8">
          {steps.map((s, i) => (
            <li
              key={s}
              className={`flex-1 text-center py-2 rounded ${
                i === step
                  ? "bg-[#1E90FF] text-white"
                  : "bg-[#1a1a1a] text-[#A3A3A3]"
              }`}
            >
              {i + 1}. {s}
            </li>
          ))}
        </ol>
        {step === 0 && <InstallStep onNext={() => setStep(1)} />}
        {step === 1 && (
          <PairStep
            onPaired={(id) => {
              setAgentId(id);
              setStep(2);
            }}
          />
        )}
        {step === 2 && agentId && (
          <DiscoverStep agentId={agentId} onNext={() => setStep(3)} />
        )}
        {step === 3 && agentId && <TestStep agentId={agentId} />}
      </div>
    </div>
  );
}
