"use client";

import React, { useEffect } from "react";

export type ToastVariant = "success" | "danger" | "info";

export function Toast({ message, content, variant = "success", onClose }: { message: string; content?: React.ReactNode; variant?: ToastVariant; onClose: () => void }) {
  useEffect(() => {
    const timeout = window.setTimeout(onClose, 5000);
    return () => window.clearTimeout(timeout);
  }, [message, onClose]);

  return (
    <div className={`toast toast-${variant}`} role={variant === "danger" ? "alert" : "status"}>
      <span className="toast-icon" aria-hidden="true">{variant === "success" ? "✓" : variant === "danger" ? "!" : "i"}</span>
      <span className="toast-content">{content ?? message}</span>
      <button className="toast-close" type="button" aria-label="Dismiss notification" onClick={onClose}>×</button>
    </div>
  );
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Confirm",
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onCancel]);

  if (!open) return null;
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onCancel(); }}>
      <section className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-dialog-title">
        <div className="confirm-dialog-header"><h2 id="confirm-dialog-title">{title}</h2><button className="toast-close" type="button" aria-label="Close confirmation" onClick={onCancel}>×</button></div>
        <p>{message}</p>
        <div className="confirm-dialog-actions"><button className="button button-secondary" type="button" onClick={onCancel}>Cancel</button><button className="button button-danger" type="button" onClick={onConfirm}>{confirmLabel}</button></div>
      </section>
    </div>
  );
}
