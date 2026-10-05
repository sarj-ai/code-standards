import { definePlugin } from "@oxlint/plugins";
import noLocationAssignRelativeDestination from "../../vendor/nextjs/no-location-assign-relative-destination.js";

export default definePlugin({
  meta: { name: "sarj-upstream-nextjs", version: "16.3.8" },
  rules: {
    "no-location-assign-relative-destination":
      noLocationAssignRelativeDestination,
  },
});
