import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle, CheckCircle2, Eye, EyeOff, FileText, Image as ImageIcon, LoaderCircle,
  Mic2, RefreshCw, Settings, ShieldCheck, Video, X,
} from 'lucide-react';

import { apiRequest } from '../../api/client';
import { t } from '../../i18n';


export type ModelCategory = 'text' | 'image' | 'video' | 'audio';

interface ProviderOption {
  id: string;
  label: string;
  default_base_url: string;
  key_hint?: string;
}

interface ProviderGroup {
  category: ModelCategory;
  providers: ProviderOption[];
}

interface DiscoveredModel {
  model_id: string;
  display_name: string;
  description: string;
  category: ModelCategory;
  subcategory: 'asr' | 'tts' | 'voice_conversion' | 'voice_design' | 'bgm' | 'music' | 'music_cover' | null;
  capabilities: string[];
}

interface ProviderServiceCapability {
  id: string;
  label: string;
  label_en: string;
  kind: 'model_backed' | 'service' | 'resource' | 'embed';
  model_ids: string[];
  provider_endpoints: string[];
  project_entrypoints: string[];
  description: string;
}

interface ConfiguredModel extends DiscoveredModel {
  id: string;
  enabled: boolean;
}

/** One more key saved for a configuration; calls rotate across the enabled keys of their bucket. */
interface ExtraCredential {
  id: string;
  label: string;
  key_hint: string;
  buckets: string[];
  enabled: boolean;
  cooling?: boolean;
  cooling_seconds_left?: number;
  last_error?: string | null;
  uses?: number;
}

interface ModelConfiguration {
  id: string;
  category: ModelCategory;
  provider: string;
  provider_label: string;
  base_url: string;
  has_api_key: boolean;
  key_hint: string;
  enabled: boolean;
  models: ConfiguredModel[];
  credentials?: ExtraCredential[];
  credential_verified?: boolean;
  warnings?: string[];
  service_capabilities?: ProviderServiceCapability[];
}


interface DeclaredVideoEndpoint {
  family: string;
  label: string;
  base_url: string;
  model_ids: string[];
  modes: string[];
  has_api_key: boolean;
  key_hint: string;
  enabled: boolean;
  ready: boolean;
  spec: Record<string, unknown>;
}

interface MarketSource { id: string; key: string; kind: string; url: string; label: string; official: boolean; enabled: boolean; fetched_at: string | null; error: string; entry_count: number; index_name: string }

interface MarketEntryRow {
  slug: string; name: string; version: string; kind: string; summary: string; author: string; tags: string[];
  source_id: string; source_key: string; source_label: string;
  installed: boolean; installed_family: string | null; installed_version: string | null;
  market_status: 'latest' | 'update_available' | 'unavailable' | null; modified: boolean;
}

interface MarketInstall {
  family: string; source_id: string; source_label: string; slug: string; name: string; version: string; available_version: string | null;
  market_status: 'latest' | 'update_available' | 'unavailable'; modified: boolean; endpoint_present: boolean;
}

const MARKET_STATUS_LABEL: Record<MarketInstall['market_status'], string> = { latest: '最新', update_available: '可更新', unavailable: '市场中不可用' };

interface ComfyStatus { family: string; label: string; configured: boolean; workflow: string; ready: boolean; problems: string[]; how_to: string }

interface CentreSettings {
  video_endpoints: DeclaredVideoEndpoint[];
  video_endpoint_placeholders: string[];
  comfyui: ComfyStatus;
}

const BUCKET_LABELS: Record<string, string> = { text: '文本', image: '图像', video: '视频', audio: '音频' };

const VIDEO_ENDPOINT_EXAMPLE = {
  label: '我的视频供应商',
  base_url: 'https://api.example.com',
  model_ids: ['my-video-v1'],
  modes: ['text', 'first_frame'],
  submit: { method: 'POST', path: '/v1/videos', body: { model: '{{model}}', prompt: '{{prompt}}', image: '{{first_frame}}', seconds: '{{duration}}' } },
  job_id_path: 'data.id',
  poll: { path: '/v1/videos/{{job_id}}', status_path: 'data.status', video_url_path: 'data.url', success: ['done'], failure: ['failed'] },
};

interface Props {
  open: boolean;
  role?: string;
  mustChangePassword?: boolean;
  onClose: () => void;
  onSelect?: (category: ModelCategory, modelId: string) => void;
  onConfigurationChange?: () => void;
}

const CATEGORY_META: Record<ModelCategory, { label: string; icon: typeof FileText }> = {
  text: { label: '文本模型', icon: FileText },
  image: { label: '图像模型', icon: ImageIcon },
  video: { label: '视频模型', icon: Video },
  audio: { label: '音频模型', icon: Mic2 },
};

const AUDIO_LABELS: Record<string, string> = {
  asr: 'ASR 语音识别',
  tts: 'TTS 配音',
  voice_conversion: '语音转换',
  voice_design: '声音设计',
  bgm: 'BGM / 音效',
  music: '音乐',
  music_cover: '音乐翻唱',
};


export function ModelConfigurationCenter({
  open,
  role = 'user',
  mustChangePassword = false,
  onClose,
  onSelect,
  onConfigurationChange,
}: Props) {
  const [category, setCategory] = useState<ModelCategory>('text');
  const [providerGroups, setProviderGroups] = useState<ProviderGroup[]>([]);
  const [configurations, setConfigurations] = useState<ModelConfiguration[]>([]);
  const [summary, setSummary] = useState<Record<ModelCategory, number>>({ text: 0, image: 0, video: 0, audio: 0 });
  const [provider, setProvider] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [models, setModels] = useState<DiscoveredModel[]>([]);
  const [serviceCapabilities, setServiceCapabilities] = useState<ProviderServiceCapability[]>([]);
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [activeCapability, setActiveCapability] = useState('');
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [centreSettings, setCentreSettings] = useState<CentreSettings | null>(null);
  const [marketSources, setMarketSources] = useState<MarketSource[]>([]);
  const [marketEntries, setMarketEntries] = useState<MarketEntryRow[]>([]);
  const [marketInstalls, setMarketInstalls] = useState<MarketInstall[]>([]);
  const [marketLoaded, setMarketLoaded] = useState(false);
  const [marketSourceUrl, setMarketSourceUrl] = useState('');
  const [marketKeys, setMarketKeys] = useState<Record<string, string>>({});
  // Extra credentials: which configuration the add form is open for, and its fields.
  const [credentialFor, setCredentialFor] = useState('');
  const [credentialLabel, setCredentialLabel] = useState('');
  const [credentialKey, setCredentialKey] = useState('');
  const [credentialBuckets, setCredentialBuckets] = useState<string[]>([]);
  const [endpointFamily, setEndpointFamily] = useState('');
  const [endpointSpec, setEndpointSpec] = useState(JSON.stringify(VIDEO_ENDPOINT_EXAMPLE, null, 2));
  const [endpointKey, setEndpointKey] = useState('');

  const reloadConfigurations = useCallback(async () => {
    const response = await apiRequest<{ items: ModelConfiguration[]; summary: Record<ModelCategory, number>; settings?: CentreSettings }>('/api/model-configurations');
    setConfigurations(response.items);
    setSummary(response.summary);
    if (response.settings) {
      setCentreSettings(response.settings);
    }
  }, []);

  const addCredential = useCallback(async (configuration: ModelConfiguration) => {
    if (credentialKey.trim().length < 6) { setError(t('备用 API Key 太短')); return; }
    setBusy(`credential:${configuration.id}`);
    setError('');
    try {
      await apiRequest(`/api/model-configurations/${configuration.id}/credentials`, {
        method: 'POST', body: JSON.stringify({ label: credentialLabel.trim(), api_key: credentialKey.trim(), buckets: credentialBuckets }),
      });
      setCredentialFor(''); setCredentialLabel(''); setCredentialKey(''); setCredentialBuckets([]);
      setMessage(t('备用凭据已加密保存；同一供应商的调用会在各把 Key 之间轮换。'));
      await reloadConfigurations();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '备用凭据保存失败');
    } finally {
      setBusy('');
    }
  }, [credentialBuckets, credentialKey, credentialLabel, reloadConfigurations]);

  const removeCredential = useCallback(async (configuration: ModelConfiguration, credential: ExtraCredential) => {
    setBusy(`credential:${credential.id}`);
    try {
      await apiRequest(`/api/model-configurations/${configuration.id}/credentials/${credential.id}`, { method: 'DELETE' });
      await reloadConfigurations();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '删除凭据失败');
    } finally {
      setBusy('');
    }
  }, [reloadConfigurations]);


  const saveEndpoint = useCallback(async () => {
    let spec: unknown;
    try { spec = JSON.parse(endpointSpec); } catch { setError(t('端点声明不是合法 JSON')); return; }
    const family = endpointFamily.trim().toLowerCase();
    if (!/^[a-z0-9_]{2,40}$/.test(family)) { setError(t('族标识只能是小写字母、数字和下划线')); return; }
    setBusy('endpoint');
    setError('');
    try {
      await apiRequest(`/api/model-configurations/settings/video-endpoints/${family}`, {
        method: 'PUT', body: JSON.stringify({ spec, api_key: endpointKey.trim() || undefined }),
      });
      setEndpointKey('');
      setMessage(t('声明式视频端点 {0} 已保存，其模型可在项目里按视频模型选用。', [family]));
      await reloadConfigurations();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '声明式端点保存失败');
    } finally {
      setBusy('');
    }
  }, [endpointFamily, endpointKey, endpointSpec, reloadConfigurations]);

  const removeEndpoint = useCallback(async (family: string) => {
    setBusy(`endpoint:${family}`);
    try {
      await apiRequest(`/api/model-configurations/settings/video-endpoints/${family}`, { method: 'DELETE' });
      await reloadConfigurations();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '删除端点失败');
    } finally {
      setBusy('');
    }
  }, [reloadConfigurations]);

  const providers = useMemo(
    () => providerGroups.find(group => group.category === category)?.providers ?? [],
    [providerGroups, category],
  );
  const savedForCategory = configurations.filter(item => item.category === category);
  const savedModelRows = savedForCategory.flatMap(configuration => (
    configuration.models.map(model => ({ configuration, model }))
  ));
  const enabledSavedCount = savedModelRows.filter(
    ({ configuration, model }) => configuration.enabled && model.enabled,
  ).length;
  const canManage = role === 'admin' && !mustChangePassword;

  const reloadMarket = useCallback(async () => {
    const [sources, entries, installs] = await Promise.all([
      apiRequest<{ items: MarketSource[] }>('/api/market/sources'),
      apiRequest<{ items: MarketEntryRow[] }>('/api/market/entries'),
      apiRequest<{ items: MarketInstall[] }>('/api/market/installed'),
    ]);
    setMarketSources(sources.items);
    setMarketEntries(entries.items);
    setMarketInstalls(installs.items);
    setMarketLoaded(true);
  }, []);

  useEffect(() => {
    if (!open || category !== 'video' || marketLoaded) return;
    let active = true;
    Promise.all([
      apiRequest<{ items: MarketSource[] }>('/api/market/sources'),
      apiRequest<{ items: MarketEntryRow[] }>('/api/market/entries'),
      apiRequest<{ items: MarketInstall[] }>('/api/market/installed'),
    ]).then(([sources, entries, installs]) => {
      if (!active) return;
      setMarketSources(sources.items);
      setMarketEntries(entries.items);
      setMarketInstalls(installs.items);
      setMarketLoaded(true);
    }).catch(reason => {
      if (active) setError(reason instanceof Error ? reason.message : t('市场加载失败'));
    });
    return () => { active = false; };
  }, [category, marketLoaded, open]);

  const marketAction = useCallback(async (key: string, run: () => Promise<unknown>, done?: string) => {
    setBusy(key);
    setError('');
    try {
      await run();
      if (done) setMessage(done);
      await reloadMarket();
      await reloadConfigurations();
    } catch (reason) {
      const detail = (reason as { detail?: { message?: string } })?.detail;
      setError(detail?.message || (reason instanceof Error ? reason.message : t('市场操作失败')));
    } finally {
      setBusy('');
    }
  }, [reloadConfigurations, reloadMarket]);

  const addMarketSource = useCallback(async () => {
    const url = marketSourceUrl.trim();
    if (!url) { setError(t('请输入市场源地址（GitHub 仓库或索引直链）')); return; }
    await marketAction('market:add', () => apiRequest('/api/market/sources', { method: 'POST', body: JSON.stringify({ url }) }), t('市场源已添加'));
    setMarketSourceUrl('');
  }, [marketAction, marketSourceUrl]);

  const installMarketEntry = useCallback(async (entry: MarketEntryRow, options: { overwrite?: boolean; discardLocal?: boolean } = {}) => {
    const keyName = `${entry.source_id}/${entry.slug}`;
    const apiKey = (marketKeys[keyName] || '').trim();
    if (!entry.installed && !apiKey) { setError(t('首次安装需要提供这个供应商的 API Key')); return; }
    await marketAction(`market:install:${keyName}`, () => apiRequest(`/api/market/sources/${entry.source_id}/entries/${entry.slug}/install`, {
      method: 'POST', body: JSON.stringify({ api_key: apiKey || undefined, overwrite: Boolean(options.overwrite), discard_local: Boolean(options.discardLocal) }),
    }), entry.installed ? t('条目 {0} 已更新到最新版本', [entry.name]) : t('条目 {0} 已安装为声明式视频端点', [entry.name]));
    setMarketKeys(current => ({ ...current, [keyName]: '' }));
  }, [marketAction, marketKeys]);

  const exportMarketBundle = useCallback(async (family: string) => {
    setBusy(`market:export:${family}`);
    setError('');
    try {
      const bundle = await apiRequest<{ slug: string; files: Record<string, string>; index_entry: unknown; note: string }>(`/api/market/export/${family}`, { method: 'POST', body: JSON.stringify({}) });
      const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `market-entry-${bundle.slug}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
      setMessage(t('条目包已导出：把其中的文件加进市场源仓库并提交 PR 即可分享（不含 API Key）'));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t('导出条目包失败'));
    } finally {
      setBusy('');
    }
  }, []);
  const activeCapabilityEntry = serviceCapabilities.find(item => item.id === activeCapability);
  const visibleModels = activeCapabilityEntry
    ? models.filter(item => activeCapabilityEntry.model_ids.includes(item.model_id))
    : models;

  const requestPayload = useCallback(
    () => ({ category, provider, base_url: baseUrl.trim(), api_key: apiKey.trim() }),
    [apiKey, baseUrl, category, provider],
  );

  const discoverModels = useCallback(async () => {
    if (!provider || !baseUrl.trim() || !apiKey.trim()) {
      setError(t('请选择供应商并填写基础 URL 与 API Key'));
      return;
    }
    setBusy('discover');
    setMessage('');
    setNotice('');
    setError('');
    try {
      const result = await apiRequest<{
        items: DiscoveredModel[];
        total: number;
        credential_verified?: boolean;
        warnings?: string[];
        service_capabilities?: ProviderServiceCapability[];
      }>(
        '/api/model-configurations/discover',
        { method: 'POST', body: JSON.stringify(requestPayload()) },
      );
      setModels(result.items);
      setServiceCapabilities(result.service_capabilities ?? []);
      setSelectedModels(current => current.filter(modelId => result.items.some(item => item.model_id === modelId)));
      setActiveCapability(current => (
        result.service_capabilities?.some(item => item.id === current) ? current : ''
      ));
      setMessage(result.total
        ? result.credential_verified === false
          ? `已加载 ${result.total} 个官方模型（凭据未验证）`
          : `已加载 ${result.total} 个可用模型`
        : '供应商没有返回当前分类的模型');
      setNotice(result.warnings?.join('；') ?? '');
    } catch (reason) {
      setModels([]);
      setServiceCapabilities([]);
      setSelectedModels([]);
      setActiveCapability('');
      setError(reason instanceof Error ? reason.message : '动态模型加载失败');
    } finally {
      setBusy('');
    }
  }, [apiKey, baseUrl, provider, requestPayload]);

  useEffect(() => {
    if (!open) return;
    let active = true;
    Promise.all([
      apiRequest<{ items: ProviderGroup[] }>('/api/model-configurations/providers'),
      apiRequest<{ items: ModelConfiguration[]; summary: Record<ModelCategory, number>; settings?: CentreSettings }>('/api/model-configurations'),
    ]).then(([providerResponse, configurationResponse]) => {
      if (!active) return;
      setProviderGroups(providerResponse.items);
      setConfigurations(configurationResponse.items);
      setSummary(configurationResponse.summary);
      if (configurationResponse.settings) {
        setCentreSettings(configurationResponse.settings);
      }
    }).catch(reason => {
      if (active) setError(reason instanceof Error ? reason.message : '模型配置加载失败');
    }).finally(() => { if (active) setBusy(''); });
    return () => { active = false; };
  }, [open]);

  useEffect(() => {
    if (!open || !canManage || !provider || !baseUrl.startsWith('https://') || apiKey.trim().length < 6) return;
    const timer = window.setTimeout(() => { void discoverModels(); }, 800);
    return () => window.clearTimeout(timer);
  }, [apiKey, baseUrl, canManage, discoverModels, open, provider]);

  if (!open) return null;

  const providerKeyHint = providers.find(item => item.id === provider)?.key_hint;
  const providerLabel = providers.find(item => item.id === provider)?.label ?? provider;

  const selectProvider = (providerId: string) => {
    const option = providers.find(item => item.id === providerId);
    setProvider(providerId);
    setBaseUrl(option?.default_base_url ?? '');
    setModels([]);
    setServiceCapabilities([]);
    setSelectedModels([]);
    setActiveCapability('');
    setMessage('');
    setNotice('');
    setError('');
  };

  const testConnection = async () => {
    if (!selectedModels.length) { setError(t('请先从动态列表选择至少一个模型')); return; }
    setBusy('test'); setError(''); setMessage(''); setNotice('');
    try {
      const result = await apiRequest<{ connected: boolean; message: string }>(
        '/api/model-configurations/test',
        { method: 'POST', body: JSON.stringify({ ...requestPayload(), selected_model_ids: selectedModels }) },
      );
      setMessage(result.message);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '连接测试失败');
    } finally { setBusy(''); }
  };

  const save = async () => {
    if (!selectedModels.length) { setError(t('请先选择至少一个模型')); return; }
    setBusy('save'); setError(''); setMessage(''); setNotice('');
    try {
      const saved = await apiRequest<ModelConfiguration>('/api/model-configurations', {
        method: 'POST',
        body: JSON.stringify({ ...requestPayload(), selected_model_ids: selectedModels }),
      });
      setConfigurations(current => [...current.filter(item => item.id !== saved.id), saved]);
      setSummary(current => ({
        ...current,
        [category]: configurations.filter(item => item.category === category && item.id !== saved.id)
          .reduce((count, item) => count + item.models.filter(model => item.enabled && model.enabled).length, 0)
          + saved.models.filter(model => saved.enabled && model.enabled).length,
      }));
      setApiKey(''); setShowKey(false); setModels([]); setServiceCapabilities([]); setSelectedModels([]); setActiveCapability('');
      setMessage(t('已安全保存 {0} 个模型并全局生效', [selectedModels.length]));
      setNotice(saved.warnings?.join('；') ?? '');
      onConfigurationChange?.();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '配置保存失败');
    } finally { setBusy(''); }
  };

  const toggleModel = async (configuration: ModelConfiguration, model: ConfiguredModel) => {
    setBusy(model.id); setError('');
    try {
      const updated = await apiRequest<{ enabled: boolean }>(
        `/api/model-configurations/${configuration.id}/models/${model.id}`,
        { method: 'PATCH', body: JSON.stringify({ enabled: !model.enabled }) },
      );
      setConfigurations(current => current.map(item => item.id !== configuration.id ? item : {
        ...item, models: item.models.map(entry => entry.id === model.id ? { ...entry, enabled: updated.enabled } : entry),
      }));
      if (configuration.enabled) {
        setSummary(current => ({ ...current, [category]: Math.max(0, current[category] + (updated.enabled ? 1 : -1)) }));
      }
      onConfigurationChange?.();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '模型状态更新失败');
    } finally { setBusy(''); }
  };

  const deleteModel = async (configuration: ModelConfiguration, model: ConfiguredModel) => {
    const busyKey = `delete:${model.id}`;
    setBusy(busyKey); setError(''); setMessage('');
    try {
      const result = await apiRequest<{
        entry_id: string;
        model_id: string;
        category: ModelCategory;
        was_enabled: boolean;
        configuration_deleted: boolean;
      }>(`/api/model-configurations/${configuration.id}/models/${model.id}`, { method: 'DELETE' });
      setConfigurations(current => current.flatMap(item => {
        if (item.id !== configuration.id) return [item];
        if (result.configuration_deleted) return [];
        return [{ ...item, models: item.models.filter(entry => entry.id !== model.id) }];
      }));
      if (result.was_enabled) {
        setSummary(current => ({
          ...current,
          [result.category]: Math.max(0, current[result.category] - 1),
        }));
      }
      setMessage(t('已删除模型 {0}', [model.display_name]));
      onConfigurationChange?.();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '模型删除失败');
    } finally { setBusy(''); }
  };

  const toggleSelectedModel = (modelId: string) => {
    setSelectedModels(current => current.includes(modelId)
      ? current.filter(item => item !== modelId)
      : [...current, modelId]);
  };

  const selectVisibleModels = () => {
    setSelectedModels(current => Array.from(new Set([
      ...current,
      ...visibleModels.map(item => item.model_id),
    ])));
  };

  const closeDialog = () => {
    setApiKey('');
    setShowKey(false);
    setModels([]);
    setServiceCapabilities([]);
    setSelectedModels([]);
    setActiveCapability('');
    setMessage('');
    setNotice('');
    setError('');
    setBusy('');
    onClose();
  };

  return (
    <div className="model-config-backdrop" role="presentation">
      <section className="model-config-dialog" role="dialog" aria-modal="true" aria-labelledby="model-config-title">
        <header className="model-config-header">
          <div className="model-config-title"><Settings aria-hidden="true" /><h2 id="model-config-title">{t('模型配置')}</h2></div>
          <div className="model-config-tabs" role="tablist" aria-label={t('模型分类')}>
            {(Object.keys(CATEGORY_META) as ModelCategory[]).map(key => {
              const Icon = CATEGORY_META[key].icon;
              return <button key={key} type="button" role="tab" aria-selected={category === key} className={category === key ? 'active' : ''} onClick={() => { setCategory(key); setProvider(''); setBaseUrl(''); setModels([]); setServiceCapabilities([]); setSelectedModels([]); setActiveCapability(''); setMessage(''); setNotice(''); setError(''); }}><Icon size={17} />{CATEGORY_META[key].label}</button>;
            })}
          </div>
          <button type="button" className="model-config-close" aria-label={t('关闭模型配置')} onClick={closeDialog}><X /></button>
        </header>

        <div className="model-category-summary" aria-label={t('已启用模型统计')}>
          {(Object.keys(CATEGORY_META) as ModelCategory[]).map(key => {
            const Icon = CATEGORY_META[key].icon;
            return <button type="button" key={key} onClick={() => setCategory(key)} className={category === key ? 'active' : ''}><Icon size={16} /><span>{CATEGORY_META[key].label}</span><strong>{summary[key]}</strong></button>;
          })}
        </div>

        <div className="model-config-body">
          <div className="model-config-form" aria-busy={Boolean(busy)}>
            {mustChangePassword && <div className="model-config-error" role="alert">{t('首次登录请先在用户中心修改管理员密码，完成后即可配置全局模型。')}</div>}
            <label htmlFor="model-provider">{t('AI 供应商')}</label>
            <select id="model-provider" aria-label={t('AI 供应商')} value={provider} onChange={event => selectProvider(event.target.value)} disabled={!canManage}>
              <option value="">{t('请选择供应商')}</option>
              {providers.map(item => <option value={item.id} key={item.id}>{item.label}</option>)}
            </select>

            <label htmlFor="model-base-url">{t('基础 URL')}</label>
            <input id="model-base-url" value={baseUrl} onChange={event => setBaseUrl(event.target.value)} placeholder={t('https://供应商官方 API 地址')} disabled={!canManage} />

            <label htmlFor="model-api-key">{t('API 密钥')}</label>
            <div className="secret-input">
              <input id="model-api-key" aria-label={t('API 密钥')} type={showKey ? 'text' : 'password'} value={apiKey} onChange={event => setApiKey(event.target.value)} autoComplete="new-password" placeholder={t('只发送到后端并加密保存')} disabled={!canManage} />
              <button type="button" onClick={() => setShowKey(value => !value)} aria-label={showKey ? t('隐藏 API 密钥') : t('显示 API 密钥')}>{showKey ? <EyeOff /> : <Eye />}</button>
            </div>
            {providerKeyHint && <p className="model-config-key-hint" data-testid="provider-key-hint">{providerKeyHint}</p>}

            <div className="model-field-heading"><label id="model-name-label">{t('模型名称')}</label><button type="button" className="reload-models" onClick={() => void discoverModels()} disabled={!canManage || busy === 'discover'}>{busy === 'discover' ? <LoaderCircle className="spin" /> : <RefreshCw />}加载模型</button></div>
            {serviceCapabilities.length > 0 && <section className="provider-service-capabilities" aria-label={`${providerLabel} 完整能力`}>
              <header><strong>{providerLabel} 完整能力</strong><span>{serviceCapabilities.length}/{serviceCapabilities.length}</span></header>
              <div className="provider-capability-filters">
                <button type="button" className={!activeCapability ? 'active' : ''} aria-pressed={!activeCapability} onClick={() => setActiveCapability('')}>
                  <span>{t('全部模型')}</span><small>{models.length} 个模型</small>
                </button>
                {serviceCapabilities.map(capability => <button type="button" key={capability.id} title={capability.description} className={activeCapability === capability.id ? 'active' : ''} aria-pressed={activeCapability === capability.id} onClick={() => setActiveCapability(capability.id)}>
                  <span>{capability.label}</span>
                  <small>{capability.model_ids.length ? `${capability.model_ids.filter(modelId => models.some(model => model.model_id === modelId)).length} 个模型` : '独立服务'}</small>
                </button>)}
              </div>
              <p>{t('点击能力分类筛选并选择模型；独立服务没有模型 ID，保存同一供应商模型后会自动调用对应接口。')}</p>
            </section>}
            <section className="model-selection-panel" role="group" aria-labelledby="model-name-label">
              <div className="model-selection-toolbar">
                <span>{models.length ? `已选择 ${selectedModels.length} 个模型` : '请先填写凭据并加载模型'}</span>
                {!!visibleModels.length && <button type="button" onClick={selectVisibleModels}>{t('全选当前分类')}</button>}
              </div>
              {activeCapabilityEntry && !activeCapabilityEntry.model_ids.length
                ? <div className="model-selection-empty"><strong>{activeCapabilityEntry.label}</strong><span>这是独立服务，无需选择模型。{activeCapabilityEntry.description}</span></div>
                : visibleModels.length
                  ? <div className="model-choice-list">{visibleModels.map(item => {
                    const label = `${item.display_name}${item.subcategory ? ` · ${AUDIO_LABELS[item.subcategory]}` : item.capabilities.includes('multimodal') ? ' · 多模态' : ''}`;
                    return <label className="model-choice" key={`${item.model_id}:${item.subcategory ?? ''}`}>
                      <input type="checkbox" checked={selectedModels.includes(item.model_id)} onChange={() => toggleSelectedModel(item.model_id)} aria-label={label} />
                      <span className="model-choice-copy"><strong>{label}</strong><code>{item.model_id}</code><small>{item.description || '供应商未提供模型说明'}</small></span>
                    </label>;
                  })}</div>
                  : <div className="model-selection-empty"><span>{models.length ? t('当前能力没有返回可选择的模型') : t('尚未加载模型')}</span></div>}
            </section>
            {error && <div className="model-config-error" role="alert">{error}</div>}
            {notice && <div className="model-config-warning" role="status"><AlertTriangle size={17} />{notice}</div>}
            {message && <div className="model-config-success" role="status"><CheckCircle2 size={17} />{message}</div>}
          </div>

          <aside className="saved-models" aria-labelledby="saved-models-title">
            <div className="saved-models-heading">
              <div><h3 id="saved-models-title">{t('已保存模型')}</h3><p>{t('只有启用状态的模型会进入项目全局选择器。')}</p></div>
              <span aria-label={t('已保存模型数量')}>共 {savedModelRows.length} 个 · 已启用 {enabledSavedCount} 个</span>
            </div>
            {savedModelRows.length === 0
              ? <div className="saved-models-empty"><ShieldCheck /><span>{t('当前分类尚未保存模型配置')}</span></div>
              : <div className="saved-model-list" aria-label={`${CATEGORY_META[category].label}已保存模型列表`}>
                {savedModelRows.map(({ configuration, model }) => (
                  <article className={`saved-model-card${configuration.enabled && model.enabled ? '' : ' is-disabled'}`} key={model.id}>
                    <div><strong>{model.display_name}</strong><span>{configuration.provider_label} · {model.subcategory ? AUDIO_LABELS[model.subcategory] : model.capabilities.includes('multimodal') ? t('文本 + 多模态') : CATEGORY_META[category].label}</span><code>{model.model_id}</code></div>
                    <div className="saved-model-actions">
                      {model.enabled && onSelect && <button type="button" onClick={() => onSelect(category, model.model_id)}>{t('设为当前')}</button>}
                      <button type="button" role="switch" aria-checked={model.enabled} aria-label={`${model.display_name} 全局启用`} className={`switch ${model.enabled ? 'on' : ''}`} disabled={!canManage || busy === model.id} onClick={() => void toggleModel(configuration, model)}><span /></button>
                      <button type="button" className="saved-model-delete" aria-label={`${model.display_name} 删除保存`} title={t('删除已保存模型')} disabled={!canManage || busy === `delete:${model.id}`} onClick={() => void deleteModel(configuration, model)}>{busy === `delete:${model.id}` ? <LoaderCircle className="spin" /> : <X />}</button>
                    </div>
                  </article>
                ))}
              </div>}

            {savedForCategory.map(configuration => (
              <section className="credential-pool" key={`pool-${configuration.id}`} aria-label={`${configuration.provider_label} 备用凭据`}>
                <header>
                  <strong>{configuration.provider_label} · 备用凭据</strong>
                  <span>主凭据 {configuration.key_hint || '已保存'} · 备用 {configuration.credentials?.length ?? 0} 把；调用按任务类型桶轮换，被拒绝的 Key 冷却后再试</span>
                  {canManage && credentialFor !== configuration.id && (
                    <button type="button" onClick={() => { setCredentialFor(configuration.id); setCredentialLabel(''); setCredentialKey(''); setCredentialBuckets([]); }}>{t('添加备用 Key')}</button>
                  )}
                </header>
                {(configuration.credentials ?? []).length > 0 && (
                  <ul>
                    {(configuration.credentials ?? []).map(credential => (
                      <li key={credential.id}>
                        <strong>{credential.label}</strong>
                        <code>{credential.key_hint}</code>
                        <span>{credential.buckets.length ? credential.buckets.map(b => BUCKET_LABELS[b] ?? b).join(' / ') : t('任意桶')}{credential.uses ? ` · 已用 ${credential.uses} 次` : ''}</span>
                        {credential.cooling && <em>冷却中（{credential.last_error}）</em>}
                        {!credential.enabled && <em>{t('已停用')}</em>}
                        {canManage && <button type="button" aria-label={`删除备用凭据 ${credential.label}`} disabled={busy === `credential:${credential.id}`} onClick={() => void removeCredential(configuration, credential)}>{t('删除')}</button>}
                      </li>
                    ))}
                  </ul>
                )}
                {credentialFor === configuration.id && (
                  <form className="credential-pool-form" onSubmit={event => { event.preventDefault(); void addCredential(configuration); }}>
                    <input aria-label={t('备用凭据名称')} value={credentialLabel} onChange={event => setCredentialLabel(event.target.value)} placeholder={t('名称（可选）')} />
                    <input aria-label={t('备用 API 密钥')} type="password" value={credentialKey} onChange={event => setCredentialKey(event.target.value)} autoComplete="new-password" placeholder={t('备用 API Key')} />
                    <div className="credential-pool-buckets" role="group" aria-label={t('任务类型桶')}>
                      {(['text', 'image', 'video', 'audio'] as const).map(bucket => (
                        <label key={bucket}><input type="checkbox" checked={credentialBuckets.includes(bucket)} onChange={() => setCredentialBuckets(current => current.includes(bucket) ? current.filter(b => b !== bucket) : [...current, bucket])} />{BUCKET_LABELS[bucket]}</label>
                      ))}
                      <small>{t('不勾选则任何任务都可用')}</small>
                    </div>
                    <div><button type="submit" disabled={busy === `credential:${configuration.id}`}>{t('保存备用 Key')}</button><button type="button" onClick={() => setCredentialFor('')}>{t('取消')}</button></div>
                  </form>
                )}
              </section>
            ))}

            {category === 'video' && centreSettings && (
              <section className="declared-endpoints" aria-label={t('声明式视频端点')}>
                <header><strong>{t('声明式视频端点')}</strong><span>用一段 JSON 描述「提交 → 读任务号 → 轮询 → 取片段」的供应商，不写代码即可接入；可用占位符：{centreSettings.video_endpoint_placeholders.map(p => `{{${p}}}`).join(' ')}</span></header>
                {centreSettings.video_endpoints.length > 0 && (
                  <ul>
                    {centreSettings.video_endpoints.map(endpoint => (
                      <li key={endpoint.family}>
                        <strong>{endpoint.label}</strong><code>{endpoint.family}</code>
                        <span>{endpoint.model_ids.join('、')} · {endpoint.modes.join(' / ')} · {endpoint.ready ? t('就绪') : t('缺 Key')}</span>
                        {(() => {
                          const install = marketInstalls.find(item => item.family === endpoint.family);
                          return install ? (
                            <em className={`market-badge is-${install.market_status}`} title={install.source_label}>
                              {t('来自市场')} · {t(MARKET_STATUS_LABEL[install.market_status])}{install.modified ? ` · ${t('已修改')}` : ''}
                            </em>
                          ) : null;
                        })()}
                        <button type="button" aria-label={`导出条目包 ${endpoint.family}`} disabled={busy === `market:export:${endpoint.family}`} onClick={() => void exportMarketBundle(endpoint.family)}>{t('导出条目包')}</button>
                        {canManage && <button type="button" aria-label={`删除端点 ${endpoint.family}`} onClick={() => void removeEndpoint(endpoint.family)}>{t('删除')}</button>}
                      </li>
                    ))}
                  </ul>
                )}
                {canManage && (
                  <form className="declared-endpoint-form" onSubmit={event => { event.preventDefault(); void saveEndpoint(); }}>
                    <input aria-label={t('端点族标识')} value={endpointFamily} onChange={event => setEndpointFamily(event.target.value)} placeholder={t('族标识，如 acme_video')} />
                    <input aria-label={t('端点 API 密钥')} type="password" value={endpointKey} onChange={event => setEndpointKey(event.target.value)} autoComplete="new-password" placeholder={t('API Key（更新已有端点时可留空）')} />
                    <textarea aria-label={t('端点声明 JSON')} rows={10} value={endpointSpec} onChange={event => setEndpointSpec(event.target.value)} />
                    <button type="submit" disabled={busy === 'endpoint'}>{t('保存端点')}</button>
                  </form>
                )}
              </section>
            )}

            {category === 'video' && (
              <section className="market" aria-label={t('市场')}>
                <header><strong>{t('市场')}</strong><span>{t('从一个或多个市场源浏览并安装声明式视频端点；市场源就是一个 GitHub 仓库或索引直链，浏览与安装只靠本地后端与仓库运转，不依赖任何中心服务或账号')}</span></header>
                <ul className="market-sources">
                  {marketSources.map(source => (
                    <li key={source.id} className={source.enabled ? '' : 'is-disabled'}>
                      <strong>{source.label}</strong>
                      {source.official && <em className="market-badge is-official">{t('官方')}</em>}
                      <code>{source.key}</code>
                      <span>{source.error ? `${t('索引不可用')}：${source.error}` : t('{0} 个条目', [String(source.entry_count)])}</span>
                      {canManage && (
                        <>
                          <button type="button" aria-label={`刷新市场源 ${source.label}`} disabled={busy === `market:refresh:${source.id}`} onClick={() => void marketAction(`market:refresh:${source.id}`, () => apiRequest(`/api/market/sources/${source.id}/refresh`, { method: 'POST', body: JSON.stringify({}) }))}>{t('刷新')}</button>
                          <button type="button" aria-label={`${source.enabled ? '停用' : '启用'}市场源 ${source.label}`} onClick={() => void marketAction(`market:toggle:${source.id}`, () => apiRequest(`/api/market/sources/${source.id}`, { method: 'PATCH', body: JSON.stringify({ enabled: !source.enabled }) }))}>{source.enabled ? t('停用') : t('启用')}</button>
                          {!source.official && <button type="button" aria-label={`删除市场源 ${source.label}`} onClick={() => void marketAction(`market:remove:${source.id}`, () => apiRequest(`/api/market/sources/${source.id}`, { method: 'DELETE' }))}>{t('删除')}</button>}
                        </>
                      )}
                    </li>
                  ))}
                </ul>
                {canManage && (
                  <form className="market-source-form" onSubmit={event => { event.preventDefault(); void addMarketSource(); }}>
                    <input aria-label={t('市场源地址')} value={marketSourceUrl} onChange={event => setMarketSourceUrl(event.target.value)} placeholder="https://github.com/owner/market-repo" />
                    <button type="submit" disabled={busy === 'market:add'}>{t('添加市场源')}</button>
                  </form>
                )}
                {marketLoaded && marketEntries.length === 0 && <p>{t('还没有可安装的条目：添加一个市场源，或刷新已有的源')}</p>}
                {marketEntries.length > 0 && (
                  <ul className="market-entries">
                    {marketEntries.map(entry => {
                      const keyName = `${entry.source_id}/${entry.slug}`;
                      const updatable = entry.installed && entry.market_status === 'update_available';
                      return (
                        <li key={keyName}>
                          <strong>{entry.name}</strong><code>{entry.slug}@{entry.version}</code>
                          <span>{entry.summary}{entry.author ? ` · ${entry.author}` : ''} · {entry.source_label}</span>
                          {entry.installed && (
                            <em className={`market-badge is-${entry.market_status ?? 'latest'}`}>
                              {t('已安装')}{entry.installed_family ? ` ${entry.installed_family}` : ''} · {t(MARKET_STATUS_LABEL[entry.market_status ?? 'latest'])}{entry.modified ? ` · ${t('已修改')}` : ''}
                            </em>
                          )}
                          {canManage && !entry.installed && (
                            <input aria-label={`API Key ${entry.slug}`} type="password" autoComplete="new-password" value={marketKeys[keyName] || ''} onChange={event => setMarketKeys(current => ({ ...current, [keyName]: event.target.value }))} placeholder={t('这个供应商的 API Key')} />
                          )}
                          {canManage && !entry.installed && <button type="button" aria-label={`安装 ${entry.slug}`} disabled={busy === `market:install:${keyName}`} onClick={() => void installMarketEntry(entry)}>{t('安装')}</button>}
                          {canManage && updatable && <button type="button" aria-label={`更新 ${entry.slug}`} disabled={busy === `market:install:${keyName}`} onClick={() => void installMarketEntry(entry, { discardLocal: entry.modified && window.confirm(t('这个端点安装后被本地修改过，更新会覆盖这些修改；要先导出条目包吗？点「取消」可先导出，点「确定」直接覆盖')) })}>{t('更新到 {0}', [entry.version])}</button>}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </section>
            )}

            {(category === 'image' || category === 'video') && centreSettings && (
              <section className={`comfyui-status ${centreSettings.comfyui.ready ? 'is-ready' : ''}`} aria-label={t('ComfyUI 状态')}>
                <header><strong>{centreSettings.comfyui.label}</strong><span>{centreSettings.comfyui.ready ? '已就绪：在项目里把图像 / 视频模型选为 comfyui 即可使用' : `未就绪：${centreSettings.comfyui.problems.join('；')}`}</span></header>
                {!centreSettings.comfyui.ready && <p>{centreSettings.comfyui.how_to}</p>}
              </section>
            )}
          </aside>
        </div>

        <footer className="model-config-footer">
          <button type="button" className="connection-test" onClick={() => void testConnection()} disabled={!canManage || Boolean(busy)}>{t('连接测试')}</button>
          <div><button type="button" className="cancel-model-config" onClick={closeDialog}>{t('取消')}</button><button type="button" className="save-model-config" onClick={() => void save()} disabled={!canManage || Boolean(busy)}>{busy === 'save' && <LoaderCircle className="spin" />}保存配置</button></div>
        </footer>
      </section>
    </div>
  );
}
