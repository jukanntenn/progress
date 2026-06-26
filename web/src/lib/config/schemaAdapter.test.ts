import { describe, expect, it } from "vitest";
import { jsonSchemaToSections } from "./schemaAdapter";
import type { JsonSchema } from "@/lib/api";

const schema: JsonSchema = {
  type: "object",
  properties: {
    language: { type: "string", title: "Language", default: "en" },
    timezone: { type: "string", format: "timezone", title: "Timezone", default: "UTC" },
    github: { $ref: "#/$defs/GitHubConfig" },
    notification: { $ref: "#/$defs/NotificationConfig" },
    repos: {
      type: "array",
      items: { $ref: "#/$defs/RepositoryConfig" },
    },
    proposal_trackers: {
      type: "array",
      items: { type: "string", enum: ["eip", "erc", "pep"] },
    },
  },
  required: ["github"],
  $defs: {
    GitHubConfig: {
      type: "object",
      title: "GitHubConfig",
      properties: {
        gh_token: {
          type: "string",
          title: "Gh Token",
          format: "password",
          writeOnly: true,
        },
        protocol: { $ref: "#/$defs/Protocol", default: "https" },
        git_timeout: { type: "integer", minimum: 1, default: 300 },
      },
      required: ["gh_token"],
    },
    Protocol: { type: "string", enum: ["https", "ssh"] },
    RepositoryConfig: {
      type: "object",
      properties: {
        url: { type: "string" },
        enabled: { type: "boolean", default: true },
      },
      required: ["url"],
    },
    NotificationConfig: {
      type: "object",
      properties: {
        channels: {
          type: "array",
          items: {
            discriminator: { propertyName: "type", mapping: {} },
            oneOf: [{ $ref: "#/$defs/FeishuChannel" }],
          },
        },
      },
    },
    FeishuChannel: {
      type: "object",
      properties: {
        type: { const: "feishu" },
        webhook_url: { type: "string", format: "password", writeOnly: true },
      },
    },
  },
};

describe("jsonSchemaToSections", () => {
  const sections = jsonSchemaToSections(schema);
  const byId = (id: string) => sections.find((s) => s.id === id)!;

  it("groups top-level scalars into a general section", () => {
    const general = byId("general");
    const paths = general.fields.map((f) => f.path);
    expect(paths).toContain("language");
    expect(paths).toContain("timezone");
  });

  it("maps nested object properties into a section with dotted paths", () => {
    const github = byId("github");
    const token = github.fields.find((f) => f.path === "github.gh_token")!;
    expect(token.type).toBe("password");
    const timeout = github.fields.find((f) => f.path === "github.git_timeout")!;
    expect(timeout.type).toBe("number");
    expect(timeout.validation?.min).toBe(1);
  });

  it("maps enum $ref to a select field", () => {
    const github = byId("github");
    const protocol = github.fields.find((f) => f.path === "github.protocol")!;
    expect(protocol.type).toBe("select");
    expect(protocol.options).toEqual(["https", "ssh"]);
  });

  it("maps object arrays to object_list with item fields", () => {
    const repos = byId("repos");
    const field = repos.fields[0];
    expect(field.type).toBe("object_list");
    expect(field.path).toBe("repos");
    expect(field.item_fields?.map((f) => f.path)).toEqual(["url", "enabled"]);
  });

  it("maps scalar enum arrays to string_list with options", () => {
    const proposals = byId("proposal_trackers");
    const field = proposals.fields[0];
    expect(field.type).toBe("string_list");
    expect(field.options).toEqual(["eip", "erc", "pep"]);
  });

  it("maps discriminated oneOf arrays to discriminated_object_list", () => {
    const notif = byId("notification");
    const field = notif.fields[0];
    expect(field.type).toBe("discriminated_object_list");
    expect(field.discriminator).toBe("type");
    expect(field.variants?.feishu).toBeTruthy();
  });

  it("orders sections as general first", () => {
    expect(sections[0].id).toBe("general");
  });
});
