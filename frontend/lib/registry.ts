import type {
  AgentProfile,
  DirectoryResource,
  GlobalMcpServer,
  GlobalTool,
  Skill,
} from "@/lib/types";

export type RegistryKind = "agents" | "skills" | "tools" | "mcp" | "directories";
export type RegistryResource = AgentProfile | Skill | GlobalTool | GlobalMcpServer | DirectoryResource;
export type RegistryStatusFilter = "all" | "enabled" | "disabled";

export const SKILL_TAG_MAX_COUNT = 12;
export const SKILL_TAG_MAX_LENGTH = 32;

export function normalizeSkillTags(values: string[]): { tags: string[]; error: string | null } {
  const tags: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    const clean = value.trim().replace(/\s+/g, " ");
    if (!clean) continue;
    if (clean.length > SKILL_TAG_MAX_LENGTH) {
      return { tags, error: `Skill tags must be ${SKILL_TAG_MAX_LENGTH} characters or fewer.` };
    }
    const key = clean.toLocaleLowerCase();
    if (!seen.has(key)) {
      tags.push(clean);
      seen.add(key);
    }
    if (tags.length > SKILL_TAG_MAX_COUNT) {
      return { tags: tags.slice(0, SKILL_TAG_MAX_COUNT), error: `Use no more than ${SKILL_TAG_MAX_COUNT} skill tags.` };
    }
  }
  return { tags, error: null };
}

export function collectSkillTags(resources: RegistryResource[]): string[] {
  const tags = resources.flatMap((resource) => "tags" in resource ? resource.tags : []);
  return [...new Map(tags.map((tag) => [tag.toLocaleLowerCase(), tag])).values()].sort((a, b) => a.localeCompare(b));
}

export function filterRegistryResources<T extends RegistryResource>(
  resources: T[],
  kind: RegistryKind,
  query: string,
  status: RegistryStatusFilter,
  selectedTags: string[],
): T[] {
  const needle = query.trim().toLocaleLowerCase();
  const tagKeys = new Set(selectedTags.map((tag) => tag.toLocaleLowerCase()));
  return resources.filter((resource) => {
    const enabled = "enabled" in resource ? resource.enabled : true;
    if (status === "enabled" && !enabled) return false;
    if (status === "disabled" && enabled) return false;
    if (kind === "skills" && tagKeys.size > 0) {
      const resourceTags = new Set((resource as Skill).tags.map((tag) => tag.toLocaleLowerCase()));
      if (![...tagKeys].some((tag) => resourceTags.has(tag))) return false;
    }
    return !needle || registrySearchText(kind, resource).includes(needle);
  });
}

function registrySearchText(kind: RegistryKind, resource: RegistryResource): string {
  const common = [resource.name, resource.description ?? ""];
  if (kind === "agents") common.push((resource as AgentProfile).system_prompt);
  if (kind === "skills") {
    const skill = resource as Skill;
    common.push(skill.instructions, ...skill.tags);
  }
  if (kind === "mcp") {
    const connector = resource as GlobalMcpServer;
    common.push(
      connector.config.transport ?? "stdio",
      connector.config.command ?? "",
      connector.config.url ?? "",
    );
  }
  if (kind === "tools") common.push(JSON.stringify((resource as GlobalTool).config));
  if (kind === "directories") common.push((resource as DirectoryResource).path);
  return common.join(" ").toLocaleLowerCase();
}
