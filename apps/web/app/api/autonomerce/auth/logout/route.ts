import { logoutOwner } from "@/lib/owner-session";
import { errorResponse, jsonResponse } from "@/lib/route-response";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(request: Request) {
  try {
    const result = await logoutOwner(request);
    const response = jsonResponse(result.status);
    response.headers.set("Set-Cookie", result.setCookie);
    return response;
  } catch (error) {
    return errorResponse(error);
  }
}
