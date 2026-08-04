import { Button } from "@nightwatch/design-system";

export function Default() {
  return <Button>Save changes</Button>;
}

export function Variants() {
  return (
    <div className="flex flex-wrap gap-2">
      <Button variant="default">Save</Button>
      <Button variant="outline">Cancel</Button>
      <Button variant="secondary">Test AI</Button>
      <Button variant="ghost">Skip</Button>
      <Button variant="destructive">Delete camera</Button>
      <Button variant="link">Learn more</Button>
    </div>
  );
}

export function Sizes() {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button size="xs">Extra small</Button>
      <Button size="sm">Small</Button>
      <Button size="default">Default</Button>
      <Button size="lg">Large</Button>
    </div>
  );
}

export function Disabled() {
  return (
    <div className="flex flex-wrap gap-2">
      <Button disabled>Saving…</Button>
      <Button variant="outline" disabled>
        Unavailable
      </Button>
    </div>
  );
}
