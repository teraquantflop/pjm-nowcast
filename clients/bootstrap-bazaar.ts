/**
 * One-shot Coinbase Bazaar bootstrap for pjm-nowcast.
 *
 * Local buyer only. Never run on Railway. The API process refuses to start
 * if EVM_PRIVATE_KEY is set on the server.
 *
 * For each paid path: unpaid POST → decode PAYMENT-REQUIRED → skip if
 * extensions.bazaar is missing → otherwise pay Base (eip155:8453) exact USDC
 * once with the bazaar declaration copied into the payment payload.
 * No retry. No second paid call to the same path.
 *
 * wrapFetchWithPayment is not used: it retries the paid call. This file uses
 * the same @x402/fetch + @x402/evm signer, one PAYMENT-SIGNATURE per path.
 */
import "dotenv/config";
import { x402Client, x402HTTPClient } from "@x402/fetch";
import { ExactEvmScheme } from "@x402/evm";
import { privateKeyToAccount } from "viem/accounts";

const BASE_NETWORK = "eip155:8453";
const DEFAULT_BASE_URL = "https://pjm-nowcast-production.up.railway.app";
/** Official x402 PaymentOption default. Stub probe 402 advertises 60. */
const OFFICIAL_MAX_TIMEOUT_SECONDS = 300;

type JsonBody = Record<string, unknown>;

type Route = {
  method: "POST";
  path: string;
  body: JsonBody;
};

const ROUTES: Route[] = [
  { method: "POST", path: "/v1/nowcast/latest", body: {} },
  { method: "POST", path: "/v1/nowcast/history", body: { hours: 24 } },
  {
    method: "POST",
    path: "/v1/nowcast/history/extended",
    body: { hours: 168 },
  },
  { method: "POST", path: "/v1/nowcast/regime", body: {} },
  { method: "POST", path: "/v1/nowcast/spreads", body: {} },
  {
    method: "POST",
    path: "/v1/nowcast/asof",
    body: { asOf: "2026-10-09T18:00:00-04:00" },
  },
  {
    method: "POST",
    path: "/v1/nowcast/snapshots",
    body: {
      from: "2026-10-09T00:00:00-04:00",
      to: "2026-10-10T00:00:00-04:00",
    },
  },
  {
    method: "POST",
    path: "/v1/spread/probability-card",
    body: { lookbackDays: 10 },
  },
];

/** v2 PaymentRequirements. No price / maxAmountRequired. */
type CanonicalAccept = {
  scheme: string;
  network: string;
  amount: string;
  asset: string;
  payTo: string;
  maxTimeoutSeconds: number;
  extra: Record<string, unknown>;
};

type Accept = Record<string, unknown> & {
  scheme?: string;
  network?: string;
  amount?: string;
  maxAmountRequired?: string;
  maxTimeoutSeconds?: number;
  payTo?: string;
  asset?: string;
  extra?: Record<string, unknown>;
};

type Challenge = {
  x402Version?: number;
  accepts?: Accept[];
  resource?: unknown;
  extensions?: { bazaar?: unknown; [k: string]: unknown };
  error?: string;
  [k: string]: unknown;
};

function baseUrl(): string {
  return (process.env.PUBLIC_BASE_URL ?? DEFAULT_BASE_URL).replace(/\/$/, "");
}

function requireBuyerKey(): `0x${string}` {
  const raw = process.env.EVM_PRIVATE_KEY?.trim() ?? "";
  if (!raw) {
    console.error(
      "EVM_PRIVATE_KEY is missing. Set a 0x hex Base key in a local .env. Do not put it on Railway.",
    );
    process.exit(1);
  }
  if (!/^0x[0-9a-fA-F]{64}$/.test(raw)) {
    console.error(
      "EVM_PRIVATE_KEY must be 0x followed by 64 hex characters.",
    );
    process.exit(1);
  }
  return raw as `0x${string}`;
}

function header(
  res: Response,
  name: string,
): string | null {
  return res.headers.get(name) ?? res.headers.get(name.toLowerCase());
}

function decodeChallenge(res: Response): Challenge | null {
  const raw =
    header(res, "PAYMENT-REQUIRED") ?? header(res, "payment-required");
  if (!raw) return null;
  try {
    return JSON.parse(Buffer.from(raw, "base64").toString("utf8")) as Challenge;
  } catch {
    return null;
  }
}

function bazaarOf(challenge: Challenge | null): unknown {
  return challenge?.extensions?.bazaar;
}

function hasBazaar(challenge: Challenge | null): boolean {
  const blob = bazaarOf(challenge);
  return blob != null && typeof blob === "object";
}

function pickBaseExact(challenge: Challenge): Accept | null {
  const accepts = challenge.accepts ?? [];
  return (
    accepts.find(
      (a) => a.network === BASE_NETWORK && (a.scheme ?? "exact") === "exact",
    ) ?? null
  );
}

function canonicalAccept(raw: Accept): CanonicalAccept | null {
  const scheme = raw.scheme;
  const network = raw.network;
  const amount = raw.amount ?? raw.maxAmountRequired;
  const asset = raw.asset;
  const payTo = raw.payTo;
  const extra = raw.extra;
  if (
    typeof scheme !== "string" ||
    typeof network !== "string" ||
    typeof amount !== "string" ||
    typeof asset !== "string" ||
    typeof payTo !== "string" ||
    extra == null ||
    typeof extra !== "object" ||
    Array.isArray(extra)
  ) {
    return null;
  }
  return {
    scheme,
    network,
    amount,
    asset,
    payTo,
    maxTimeoutSeconds: OFFICIAL_MAX_TIMEOUT_SECONDS,
    extra,
  };
}

function echoBazaar<T extends { extensions?: Record<string, unknown> }>(
  payload: T,
  bazaar: unknown,
): T {
  const extensions = {
    ...(payload.extensions ?? {}),
    bazaar,
  };
  return { ...payload, extensions };
}

function bazaarEchoed(payload: { extensions?: { bazaar?: unknown } }, bazaar: unknown): boolean {
  try {
    return JSON.stringify(payload.extensions?.bazaar) === JSON.stringify(bazaar);
  } catch {
    return false;
  }
}

async function requireCdpBase(url: string): Promise<void> {
  const res = await fetch(`${url}/health`);
  if (!res.ok) {
    console.error(`GET /health → ${res.status}. Refusing to pay.`);
    process.exit(1);
  }
  const body = (await res.json()) as {
    facilitators?: { base?: string; cdp?: boolean };
  };
  const rail = body.facilitators?.base;
  console.log(`GET /health facilitators.base=${rail ?? "(missing)"}`);
  if (rail !== "cdp") {
    console.error(
      "Coinbase Bazaar needs a Base settle through the CDP facilitator. " +
        `This host reports base=${rail}. Set CDP_API_KEY_ID and CDP_API_KEY_SECRET on the server, then rerun.`,
    );
    process.exit(1);
  }
}

async function unpaid(
  url: string,
  route: Route,
): Promise<{ status: number; challenge: Challenge | null }> {
  const res = await fetch(`${url}${route.path}`, {
    method: route.method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(route.body),
  });
  return { status: res.status, challenge: decodeChallenge(res) };
}

async function main(): Promise<void> {
  const url = baseUrl();
  const pk = requireBuyerKey();
  const account = privateKeyToAccount(pk);
  console.log(`baseUrl=${url}`);
  console.log(`buyer=${account.address}`);
  console.log(`network=${BASE_NETWORK} asset=USDC scheme=exact`);
  console.log("[warn] Mainnet USDC. One paid call per path. No retry.");

  await requireCdpBase(url);

  const scheme = new ExactEvmScheme(account);
  const client = new x402Client();
  client.register(BASE_NETWORK, scheme);
  const http = new x402HTTPClient(client);

  let paidOk = 0;
  let skipped = 0;
  let failed = 0;

  for (const route of ROUTES) {
    const probe = await unpaid(url, route);
    if (probe.status !== 402 || !probe.challenge) {
      console.error(
        `SKIP ${route.method} ${route.path} unpaid=${probe.status} (expected 402 + PAYMENT-REQUIRED)`,
      );
      skipped += 1;
      continue;
    }
    if (!hasBazaar(probe.challenge)) {
      console.error(
        `SKIP ${route.method} ${route.path} extensions.bazaar missing — not paying`,
      );
      skipped += 1;
      continue;
    }
    const rawAccept = pickBaseExact(probe.challenge);
    if (!rawAccept) {
      console.error(
        `SKIP ${route.method} ${route.path} no eip155:8453 exact accept`,
      );
      skipped += 1;
      continue;
    }
    const accepted = canonicalAccept(rawAccept);
    if (!accepted) {
      console.error(
        `SKIP ${route.method} ${route.path} Base accept missing canonical v2 fields`,
      );
      skipped += 1;
      continue;
    }

    const bazaar = bazaarOf(probe.challenge);
    let payload: {
      x402Version: number;
      accepted: CanonicalAccept;
      extensions?: { bazaar?: unknown; [k: string]: unknown };
      [k: string]: unknown;
    };
    try {
      const created = await http.createPaymentPayload({
        x402Version: 2,
        resource: probe.challenge.resource,
        accepts: [accepted],
        extensions: probe.challenge.extensions,
      } as never);
      payload = echoBazaar(
        {
          ...created,
          x402Version: 2,
          accepted,
        },
        bazaar,
      );
    } catch (err) {
      console.error(
        `FAIL ${route.method} ${route.path} createPaymentPayload:`,
        err instanceof Error ? err.message : err,
      );
      failed += 1;
      continue;
    }
    const echoed = bazaarEchoed(payload, bazaar);
    if (!echoed) {
      console.error(
        `SKIP ${route.method} ${route.path} bazaar was not copied into the payment payload`,
      );
      skipped += 1;
      continue;
    }

    console.log(`accepted ${JSON.stringify(payload.accepted)}`);

    const paymentHeaders = http.encodePaymentSignatureHeader(payload as never);
    const headerName = Object.keys(paymentHeaders)[0] ?? "PAYMENT-SIGNATURE";
    const paid = await fetch(`${url}${route.path}`, {
      method: route.method,
      headers: {
        "Content-Type": "application/json",
        ...paymentHeaders,
      },
      body: JSON.stringify(route.body),
    });
    const result = await http.processResponse(paid);
    console.log(
      [
        `method=${route.method}`,
        `path=${route.path}`,
        `amount=${accepted.amount}`,
        `payTo=${accepted.payTo}`,
        `asset=${accepted.asset}`,
        `bazaarEchoed=${echoed}`,
        `httpStatus=${paid.status}`,
        `paymentStatus=${result.paymentStatus}`,
      ].join(" "),
    );

    if (paid.status >= 200 && paid.status < 300 && result.paymentStatus === "settled") {
      paidOk += 1;
    } else {
      failed += 1;
      const err =
        result.header && typeof result.header === "object" && "error" in result.header
          ? String((result.header as { error?: unknown }).error)
          : JSON.stringify(result.body ?? null);
      console.error(`  request header: ${headerName}`);
      console.error(`  response error: ${err}`);
    }
  }

  console.log(`done paidOk=${paidOk} skipped=${skipped} failed=${failed}`);
  if (failed > 0 || paidOk === 0) {
    process.exit(2);
  }
}

main().catch((err) => {
  console.error("bootstrap-bazaar failed:", err);
  process.exit(1);
});
