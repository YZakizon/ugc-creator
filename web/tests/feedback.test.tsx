import React, { useState } from "react";
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Toast } from "../components/feedback";

function ReRenderingToast() {
  const [visible, setVisible] = useState(true);
  const [_count, setCount] = useState(0);

  return <div>
    <button type="button" onClick={() => setCount((count) => count + 1)}>Rerender</button>
    {visible && <Toast message="Saved." onClose={() => setVisible(false)} />}
  </div>;
}

describe("Toast", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("auto-hides five seconds after showing even when parent rerenders", () => {
    vi.useFakeTimers();
    render(<ReRenderingToast />);

    expect(screen.getByRole("status")).toHaveTextContent("Saved.");

    act(() => {
      vi.advanceTimersByTime(3000);
    });
    screen.getByRole("button", { name: "Rerender" }).click();
    act(() => {
      vi.advanceTimersByTime(1999);
    });

    expect(screen.getByRole("status")).toHaveTextContent("Saved.");

    act(() => {
      vi.advanceTimersByTime(1);
    });

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
