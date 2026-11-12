# api-types

TypeScript types and typed `openapi-fetch` clients for the Nova API.

```bash
pnpm --filter api-types schema     # regenerate openapi.yaml from the Django API
pnpm --filter api-types generate   # openapi.yaml -> src/schema.d.ts
pnpm --filter api-types build      # -> dist/
```

```ts
import { createManagementClient, type Schemas } from "api-types";

const api = createManagementClient({ baseUrl: process.env.NEXT_PUBLIC_API_URL! });
const { data, error } = await api.GET("/api/manage/orgs/{org}/sites/", {
  params: { path: { org: "culture-interest" } },
});
```

`openapi.yaml` and `src/schema.d.ts` are generated and committed; a backend test fails if
`openapi.yaml` falls out of date with the API.
