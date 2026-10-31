// errors.ts — translate backend error strings for display.
//
// The API keeps returning English strings (stable contract, also used by the
// admin side). The frontend maps the known ones to translation keys; anything
// unknown is shown as the backend sent it.

import type { TFunction } from "i18next";

const EXACT: Record<string, string> = {
  "Activation token has expired": "errors.tokenExpired",
  "Current password is incorrect": "errors.currentPasswordIncorrect",
  "User not yet activated": "errors.userNotYetActivated",
  "Invalid email or password": "errors.invalidCredentials",
  "Invalid credentials": "errors.invalidCredentials",
  "An account with this email already exists": "errors.accountAlreadyExists",
  "Library not found": "errors.libraryNotFound",
  "Library is already marked as finished": "errors.libraryAlreadyFinished",
  "You must like at least one photo before finishing": "errors.mustLikeAtLeastOne",
  "Downloads are not enabled for this library": "errors.downloadsNotEnabled",
  "Public uploads are not enabled for this library": "errors.publicUploadsNotEnabled",
  "Watermark must be a PNG image": "errors.watermarkMustBePng",
  "Watermark file too large (max 5 MB)": "errors.watermarkTooLarge",
  "Storage error. Please try again.": "errors.storageError",
  "Unsupported language": "errors.unsupportedLanguage",
  "Video processing timed out": "errors.videoTimeout",
  "Upload network error": "errors.uploadNetwork",
  "Network error": "errors.uploadNetwork",
  "Upload aborted": "errors.uploadAborted",
  "Image not found": "errors.imageNotFound",
  "Video not found": "errors.videoNotFound",
  "Video uploads are not enabled": "errors.videoUploadsNotEnabled",
  "Invalid Google token": "errors.invalidGoogleToken",
  "Invalid or expired code": "errors.invalidCode",
  "Invalid activation token": "errors.invalidActivationToken",
  "No file selected": "errors.noFile",
  "No file provided": "errors.noFile",
  "File content does not match its declared type": "errors.fileTypeMismatch",
  "File is not a valid PNG image": "errors.watermarkMustBePng",
  "Unable to submit ticket. Please try again later.": "errors.ticketSubmitFailed",
  "Unable to submit feedback. Please try again later.": "errors.feedbackSubmitFailed",
};

const CODES: Record<string, string> = {
  token_expired: "errors.tokenExpired",
};

export function getApiErrorMessage(error: unknown, t: TFunction): string {
  const err = error as { message?: string; code?: string } | null | undefined;
  if (err?.code && CODES[err.code]) return t(CODES[err.code]);

  const message = err?.message;
  if (!message) return t("errors.unknown");
  if (EXACT[message]) return t(EXACT[message]);
  if (/not yet activated/i.test(message)) return t("errors.userNotYetActivated");

  const failed = message.match(/^(Request|Upload) failed \((\d+)\)$/);
  if (failed) return t("errors.requestFailed", { status: failed[2] });

  const maxLength = message.match(/(?:name|body|subject) must be (\d+) characters or fewer/i);
  if (maxLength) return t("errors.maxLength", { max: Number(maxLength[1]) });

  return message;
}
