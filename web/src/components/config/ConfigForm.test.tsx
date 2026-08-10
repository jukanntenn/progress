/**
 * Unit tests for the RJSF base-ui theme + ConfigForm (spec 8.3).
 *
 * Exercises: password widget (type + eye toggle), ui:emptyValue null→"",
 * AJV submit validation, extraErrors (backend 422 → field level), the
 * discriminated-union channels list (add/remove/reorder), group card
 * headings, and mergeInitialData default-merging.
 */

import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nextProvider } from 'react-i18next'
import i18n from '@/i18n'
import { ConfigForm } from '@/components/config/ConfigForm'
import { PasswordWidget } from '@/components/config/PasswordWidget'
import { mergeInitialData } from '@/lib/rjsf-theme/mergeInitialData'

/** Mirrors the backend's core section schema shape (Pydantic output). */
function coreSchema() {
  return {
    $defs: {
      GitHubConfig: {
        title: 'GitHubConfig',
        type: 'object',
        additionalProperties: false,
        properties: {
          gh_token: {
            type: 'string',
            format: 'password',
            title: 'GitHub Access Token',
            description: 'Personal access token.',
            default: '',
          },
          proxy: {
            type: 'string',
            title: 'HTTP Proxy',
            description: 'Optional proxy.',
            default: '',
          },
        },
      },
      NotificationConfig: {
        title: 'NotificationConfig',
        type: 'object',
        additionalProperties: false,
        properties: {
          channels: {
            type: 'array',
            title: 'Notification Channels',
            description: 'Delivery methods.',
            items: {
              discriminator: { propertyName: 'type' },
              oneOf: [
                { $ref: '#/$defs/EmailChannelConfig' },
                { $ref: '#/$defs/FeishuChannelConfig' },
              ],
            },
          },
        },
      },
      EmailChannelConfig: {
        title: 'EmailChannelConfig',
        type: 'object',
        additionalProperties: false,
        properties: {
          type: { type: 'string', const: 'email' },
          enabled: { type: 'boolean', title: 'Enable This Channel', default: true },
          host: { type: 'string', title: 'SMTP Host', default: '' },
          password: { type: 'string', format: 'password', title: 'SMTP Password', default: '' },
          recipient: { type: 'array', items: { type: 'string' }, title: 'Recipients', default: [] },
        },
      },
      FeishuChannelConfig: {
        title: 'FeishuChannelConfig',
        type: 'object',
        additionalProperties: false,
        properties: {
          type: { type: 'string', const: 'feishu' },
          enabled: { type: 'boolean', title: 'Enable This Channel', default: true },
          webhook_url: { type: 'string', format: 'password', title: 'Webhook URL', default: '' },
        },
      },
    },
    type: 'object',
    additionalProperties: false,
    properties: {
      language: { type: 'string', title: 'Language', default: 'en' },
      github: { $ref: '#/$defs/GitHubConfig' },
      notification: { $ref: '#/$defs/NotificationConfig' },
    },
  }
}

function renderForm(props: Partial<Parameters<typeof ConfigForm>[0]> = {}) {
  const onChange = vi.fn()
  const onSubmit = vi.fn()
  const onError = vi.fn()
  const view = render(
    <I18nextProvider i18n={i18n}>
      <ConfigForm
        sectionName="core"
        schema={coreSchema() as never}
        formData={{}}
        onChange={onChange}
        onSubmit={onSubmit}
        onError={onError}
        {...props}
      />
    </I18nextProvider>,
  )
  return { ...view, onChange, onSubmit, onError }
}

function submitForm() {
  const form = document.querySelector('form') as HTMLFormElement
  fireEvent.submit(form)
}

describe('PasswordWidget', () => {
  it('renders type=password and toggles to text on eye click', () => {
    const props = {
      id: 'root_github_gh_token',
      name: 'root_github_gh_token',
      label: 'GitHub Access Token',
      value: 'ghp_REAL',
      onChange: vi.fn(),
      onBlur: vi.fn(),
      onFocus: vi.fn(),
      schema: { type: 'string' } as never,
      options: {},
      registry: {
        templates: {},
        widgets: {},
        formContext: {},
        rootSchema: {},
        schemaUtils: {} as never,
        translateString: (() => '') as never,
        globalFormOptions: {},
      } as never,
      uiSchema: {},
      formContext: {},
      required: false,
      disabled: false,
      readonly: false,
    }
    render(
      <I18nextProvider i18n={i18n}>
        <PasswordWidget {...props} />
      </I18nextProvider>,
    )
    const input = screen.getByDisplayValue('ghp_REAL') as HTMLInputElement
    expect(input.type).toBe('password')

    fireEvent.click(screen.getByRole('button', { name: 'Show password' }))
    expect((screen.getByDisplayValue('ghp_REAL') as HTMLInputElement).type).toBe('text')
    fireEvent.click(screen.getByRole('button', { name: 'Hide password' }))
    expect((screen.getByDisplayValue('ghp_REAL') as HTMLInputElement).type).toBe('password')
  })

  it('emits emptyValue when the field is cleared', () => {
    const onChange = vi.fn()
    const props = {
      id: 'root_github_gh_token',
      name: 'root_github_gh_token',
      label: 'GitHub Access Token',
      value: 'ghp_REAL',
      onChange,
      onBlur: vi.fn(),
      onFocus: vi.fn(),
      schema: { type: 'string', format: 'password' } as never,
      options: {},
      uiSchema: { 'ui:emptyValue': '' },
      registry: {
        templates: {},
        widgets: {},
        formContext: {},
        rootSchema: {},
        schemaUtils: {} as never,
        translateString: (() => '') as never,
        globalFormOptions: {},
      } as never,
      formContext: {},
      required: false,
      disabled: false,
      readonly: false,
    }
    render(
      <I18nextProvider i18n={i18n}>
        <PasswordWidget {...props} />
      </I18nextProvider>,
    )
    const input = screen.getByDisplayValue('ghp_REAL') as HTMLInputElement
    fireEvent.change(input, { target: { value: '' } })
    expect(onChange).toHaveBeenCalledWith('')
  })
})

describe('ConfigForm rendering', () => {
  it('renders group cards with heading labels from def titles', () => {
    renderForm()
    const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)
    expect(headings).toContain('Core')
    expect(headings).toContain('GitHub')
    expect(headings).toContain('Notification')
  })

  it('renders password fields with the eye toggle and masks by default', () => {
    renderForm({ formData: { github: { gh_token: 'ghp_SECRET' } } })
    const input = screen.getByDisplayValue('ghp_SECRET') as HTMLInputElement
    expect(input.type).toBe('password')
    expect(screen.getByRole('button', { name: 'Show password' })).toBeInTheDocument()
  })

  it('shows field descriptions as help text', () => {
    renderForm()
    expect(screen.getByText('Personal access token.')).toBeInTheDocument()
    expect(screen.getByText('Optional proxy.')).toBeInTheDocument()
  })

  it('clearing a password field yields "" not null (ui:emptyValue)', async () => {
    const view = renderForm({ formData: { github: { gh_token: 'ghp_SECRET' } } })
    const input = screen.getByDisplayValue('ghp_SECRET') as HTMLInputElement
    await userEvent.clear(input)
    const lastCall = view.onChange.mock.calls.at(-1) as [Record<string, unknown>]
    expect((lastCall[0].github as Record<string, unknown>).gh_token).toBe('')
  })
})

describe('ConfigForm validation', () => {
  it('submits valid data to onSubmit', async () => {
    const view = renderForm({ formData: { language: 'zh-Hans' } })
    submitForm()
    await waitFor(() => expect(view.onSubmit).toHaveBeenCalled())
    const submitted = (view.onSubmit.mock.calls[0] as [Record<string, unknown>])[0]
    expect(submitted.language).toBe('zh-Hans')
  })

  it('blocks unknown fields (additionalProperties:false) with field error', async () => {
    const view = renderForm({ formData: { unknown_field: 'x' } })
    submitForm()
    await waitFor(() => expect(view.onSubmit).not.toHaveBeenCalled())
    await waitFor(() => expect(view.onError).toHaveBeenCalled())
  })

  it('submits valid nested data', async () => {
    const view = renderForm({ formData: { github: { gh_token: 'a', proxy: 'b' } } })
    submitForm()
    await waitFor(() => expect(view.onSubmit).toHaveBeenCalled())
  })

  it('injects extraErrors (backend 422) at field level', async () => {
    renderForm({
      formData: { github: { gh_token: 'a' } },
      extraErrors: { github: { gh_token: { __errors: ['Input should be a valid string'] } } },
    })
    await waitFor(() => {
      expect(screen.getByText('Input should be a valid string')).toBeInTheDocument()
    })
  })
})

describe('SelectWidget enum display', () => {
  it('shows the selected option label even when placeholder is empty', async () => {
    const { default: SelectWidget } = await import('@/lib/rjsf-theme/Widgets/SelectWidget')
    const props = {
      id: 'root_trackers_0_parser_type',
      name: 'root_trackers_0_parser_type',
      label: 'Parser Type',
      value: 'markdown_heading',
      placeholder: '',
      onChange: vi.fn(),
      onBlur: vi.fn(),
      onFocus: vi.fn(),
      schema: { type: 'string', enum: ['auto', 'markdown_heading', 'html_generic'] } as never,
      options: {
        enumOptions: [
          { value: 'auto', label: 'auto' },
          { value: 'markdown_heading', label: 'markdown_heading' },
          { value: 'html_generic', label: 'html_generic' },
        ],
      },
      registry: {} as never,
      formContext: {},
      required: false,
      disabled: false,
      readonly: false,
    }
    render(
      <I18nextProvider i18n={i18n}>
        <SelectWidget {...props} />
      </I18nextProvider>,
    )
    const trigger = screen.getByRole('combobox')
    expect(trigger.textContent?.trim()).toBe('markdown_heading')
  })
})

describe('ConfigForm channels list', () => {
  it('renders existing channels as cards and adds a new one', async () => {
    const view = renderForm({
      formData: {
        notification: {
          channels: [
            { type: 'email', enabled: true, host: 'smtp.x', password: 'pw', recipient: [] },
          ],
        },
      },
    })
    expect(screen.getByText('Channel #1')).toBeInTheDocument()
    const addButton = document.getElementById(
      'root_notification_channels__add',
    ) as HTMLButtonElement
    await userEvent.click(addButton)
    await waitFor(() => {
      const lastCall = view.onChange.mock.calls.at(-1) as [Record<string, unknown>]
      const channels = (lastCall[0].notification as Record<string, unknown>).channels as Record<
        string,
        unknown
      >[]
      expect(channels.length).toBe(2)
      expect(channels[1]).toHaveProperty('type')
    })
  })

  it('removes a channel and keeps the remaining secrets intact', async () => {
    const view = renderForm({
      formData: {
        notification: {
          channels: [
            { type: 'feishu', webhook_url: 'hook1' },
            { type: 'email', enabled: true, host: 'smtp.x', password: 'pwd1', recipient: [] },
          ],
        },
      },
    })
    const cards = screen.getAllByText(/^Channel #/)
    expect(cards.length).toBe(2)
    await userEvent.click(screen.getAllByRole('button', { name: 'Remove' })[0] as HTMLElement)
    await waitFor(() => {
      const lastCall = view.onChange.mock.calls.at(-1) as [Record<string, unknown>]
      const channels = (lastCall[0].notification as Record<string, unknown>).channels as Record<
        string,
        unknown
      >[]
      expect(channels).toHaveLength(1)
      const first = channels[0] as Record<string, unknown>
      expect(first.type).toBe('email')
      expect(first.password).toBe('pwd1')
    })
  })
})

describe('mergeInitialData', () => {
  it('fills schema defaults while keeping submitted values', () => {
    const schema = {
      type: 'object',
      properties: {
        language: { type: 'string', default: 'en' },
        github: {
          type: 'object',
          properties: {
            gh_token: { type: 'string', default: '' },
            proxy: { type: 'string', default: '' },
          },
        },
      },
    }
    const out = mergeInitialData(schema as never, { language: 'zh-Hans' })
    expect(out.language).toBe('zh-Hans')
    expect((out.github as Record<string, unknown>).gh_token).toBe('')
  })
})
