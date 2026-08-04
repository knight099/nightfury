// Stand-in for frontend/src/lib/tour.ts — no-op, so components that
// reference the onboarding tour render without pulling in driver.js
// or touching localStorage.
export function startOnboardingTour(_onComplete?: () => void) {}

export function shouldShowTour(): boolean {
  return false;
}

export function resetTour() {}
