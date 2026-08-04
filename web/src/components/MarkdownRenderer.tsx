import Markdown from 'react-markdown'
import remarkBreaks from 'remark-breaks'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import rehypeSlug from 'rehype-slug'
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize'
import type { Components } from 'react-markdown'

const schema: typeof defaultSchema = {
  ...defaultSchema,
  tagNames: [...(defaultSchema.tagNames ?? []), 'details', 'summary'],
  attributes: {
    ...defaultSchema.attributes,
    // Allow id on every element so rehype-slug heading anchors survive sanitize
    // (used by the report TOC for scroll-spy).
    '*': [...(defaultSchema.attributes?.['*'] ?? []), 'id'],
    code: [...(defaultSchema.attributes?.code ?? []), ['className']],
    a: [...(defaultSchema.attributes?.a ?? []), 'target', 'rel'],
    details: [...(defaultSchema.attributes?.details ?? []), 'open'],
  },
  protocols: {
    ...defaultSchema.protocols,
    href: [...(defaultSchema.protocols?.href ?? []), 'http', 'https', 'mailto', 'irc'],
  },
}

const components: Components = {
  a({ href, children, ...props }) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
        {children}
      </a>
    )
  },
}

interface MarkdownRendererProps {
  content: string
  className?: string
}

export function MarkdownRenderer({ content, className }: MarkdownRendererProps) {
  return (
    <div className={`prose-progress ${className ?? ''}`}>
      <Markdown
        remarkPlugins={[remarkBreaks, remarkGfm]}
        // Pipeline order matters: raw parses inline HTML (<details>/<summary>)
        // emitted by the backend's report templates into hast nodes; slug then
        // adds heading ids; sanitize runs last and its allowlist (which now
        // includes details/summary + id) keeps the safe nodes and drops the
        // rest. Without rehype-raw, <details> in markdown renders as inert text.
        rehypePlugins={[rehypeRaw, rehypeSlug, [rehypeSanitize, schema]]}
        components={components}
      >
        {content}
      </Markdown>
    </div>
  )
}
