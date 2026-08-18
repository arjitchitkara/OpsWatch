"use strict";

function formatRelativeTime(date, now) {
  const elapsedSeconds = Math.round((date.getTime() - now.getTime()) / 1000);
  const ranges = [
    { limit: 60, divisor: 1, unit: "second" },
    { limit: 3600, divisor: 60, unit: "minute" },
    { limit: 86400, divisor: 3600, unit: "hour" },
    { limit: 604800, divisor: 86400, unit: "day" },
    { limit: 2629800, divisor: 604800, unit: "week" },
    { limit: Number.POSITIVE_INFINITY, divisor: 2629800, unit: "month" },
  ];
  const selectedRange = ranges.find((range) => Math.abs(elapsedSeconds) < range.limit);
  const value = Math.round(elapsedSeconds / selectedRange.divisor);
  return new Intl.RelativeTimeFormat(undefined, { numeric: "auto" }).format(value, selectedRange.unit);
}

function updateDisplayedTimes() {
  const now = new Date();
  const exactFormatter = new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  });

  document.querySelectorAll("time[data-local-time]").forEach((timeElement) => {
    const date = new Date(timeElement.dateTime);
    if (Number.isNaN(date.getTime())) {
      return;
    }
    timeElement.textContent = formatRelativeTime(date, now);
    timeElement.title = exactFormatter.format(date);
  });
}

function prepareForms() {
  document.querySelectorAll("form").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const confirmationMessage = form.dataset.confirm;
      if (confirmationMessage && !window.confirm(confirmationMessage)) {
        event.preventDefault();
        return;
      }

      if (!form.checkValidity()) {
        return;
      }

      const submitButton = form.querySelector('button[type="submit"]');
      if (submitButton) {
        submitButton.disabled = true;
        submitButton.classList.add("btn-disabled");
        submitButton.textContent = submitButton.dataset.submittingLabel || "Working…";
      }
    });
  });
}

function prepareDismissButtons() {
  document.querySelectorAll("[data-dismiss]").forEach((button) => {
    button.addEventListener("click", () => {
      const target = document.getElementById(button.dataset.dismiss);
      if (target) {
        target.remove();
      }
    });
  });
}

function prepareOverviewRefresh() {
  const refreshSeconds = Number(document.body.dataset.autoRefreshSeconds || 0);
  if (!refreshSeconds) {
    return;
  }

  window.setTimeout(() => {
    if (document.visibilityState === "visible") {
      window.location.reload();
    }
  }, refreshSeconds * 1000);
}

updateDisplayedTimes();
prepareForms();
prepareDismissButtons();
prepareOverviewRefresh();
window.setInterval(updateDisplayedTimes, 30000);
