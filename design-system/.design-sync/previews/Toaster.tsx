import { useEffect } from "react";
import { toast } from "sonner";
import { Toaster } from "@nightwatch/design-system";

export function Default() {
  useEffect(() => {
    toast("Front Gate camera added", {
      description: "We'll start analyzing frames within a few seconds.",
    });
  }, []);
  return <Toaster />;
}

export function Variants() {
  useEffect(() => {
    toast.success("Alert rule saved");
    setTimeout(() => toast.error("Couldn't connect to Backyard camera"), 150);
    setTimeout(() => toast.warning("Daily AI quota is at 80%"), 300);
  }, []);
  return <Toaster />;
}
