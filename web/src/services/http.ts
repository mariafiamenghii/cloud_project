export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, body: unknown) {
    super(
      body && typeof body === "object" && "error" in body && typeof body.error === "string"
        ? body.error
        : `API request failed: ${status}`
    );
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

export async function readApiResponse(response: Response): Promise<unknown> {
  if (response.status === 204) return null;
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, body);
  if (body === null) throw new Error("Invalid API response");
  return body;
}

export function isMissingOrder(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404 &&
    !!error.body && typeof error.body === "object" &&
    "error" in error.body && error.body.error === "Order not found";
}
