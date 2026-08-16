import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle, CheckCircle2, Eye, EyeOff, FileText, Image as ImageIcon, LoaderCircle,
  Mic2, RefreshCw, Settings, ShieldCheck, Video, X,
} from 'lucide-react';

import { apiRequest } from '../../api/client';


export type ModelCategory = 'text' | 'image' | 'video' | 'audio';

interface ProviderOption {
  id: string;
  label: string;
  default_base_url: string;
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
  credential_verified?: boolean;
  warnings?: string[];
  service_capabilities?: ProviderServiceCapability[];
}

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
      setError('请选择供应商并填写基础 URL 与 API Key');
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
      apiRequest<{ items: ModelConfiguration[]; summary: Record<ModelCategory, number> }>('/api/model-configurations'),
    ]).then(([providerResponse, configurationResponse]) => {
      if (!active) return;
      setProviderGroups(providerResponse.items);
      setConfigurations(configurationResponse.items);
      setSummary(configurationResponse.summary);
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
    if (!selectedModels.length) { setError('请先从动态列表选择至少一个模型'); return; }
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
    if (!selectedModels.length) { setError('请先选择至少一个模型'); return; }
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
      setMessage(`已安全保存 ${selectedModels.length} 个模型并全局生效`);
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
      setMessage(`已删除模型 ${model.display_name}`);
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
          <div className="model-config-title"><Settings aria-hidden="true" /><h2 id="model-config-title">模型配置</h2></div>
          <div className="model-config-tabs" role="tablist" aria-label="模型分类">
            {(Object.keys(CATEGORY_META) as ModelCategory[]).map(key => {
              const Icon = CATEGORY_META[key].icon;
              return <button key={key} type="button" role="tab" aria-selected={category === key} className={category === key ? 'active' : ''} onClick={() => { setCategory(key); setProvider(''); setBaseUrl(''); setModels([]); setServiceCapabilities([]); setSelectedModels([]); setActiveCapability(''); setMessage(''); setNotice(''); setError(''); }}><Icon size={17} />{CATEGORY_META[key].label}</button>;
            })}
          </div>
          <button type="button" className="model-config-close" aria-label="关闭模型配置" onClick={closeDialog}><X /></button>
        </header>

        <div className="model-category-summary" aria-label="已启用模型统计">
          {(Object.keys(CATEGORY_META) as ModelCategory[]).map(key => {
            const Icon = CATEGORY_META[key].icon;
            return <button type="button" key={key} onClick={() => setCategory(key)} className={category === key ? 'active' : ''}><Icon size={16} /><span>{CATEGORY_META[key].label}</span><strong>{summary[key]}</strong></button>;
          })}
        </div>

        <div className="model-config-body">
          <div className="model-config-form" aria-busy={Boolean(busy)}>
            {mustChangePassword && <div className="model-config-error" role="alert">首次登录请先在用户中心修改管理员密码，完成后即可配置全局模型。</div>}
            <label htmlFor="model-provider">AI 供应商</label>
            <select id="model-provider" aria-label="AI 供应商" value={provider} onChange={event => selectProvider(event.target.value)} disabled={!canManage}>
              <option value="">请选择供应商</option>
              {providers.map(item => <option value={item.id} key={item.id}>{item.label}</option>)}
            </select>

            <label htmlFor="model-base-url">基础 URL</label>
            <input id="model-base-url" value={baseUrl} onChange={event => setBaseUrl(event.target.value)} placeholder="https://供应商官方 API 地址" disabled={!canManage} />

            <label htmlFor="model-api-key">API 密钥</label>
            <div className="secret-input">
              <input id="model-api-key" aria-label="API 密钥" type={showKey ? 'text' : 'password'} value={apiKey} onChange={event => setApiKey(event.target.value)} autoComplete="new-password" placeholder="只发送到后端并加密保存" disabled={!canManage} />
              <button type="button" onClick={() => setShowKey(value => !value)} aria-label={showKey ? '隐藏 API 密钥' : '显示 API 密钥'}>{showKey ? <EyeOff /> : <Eye />}</button>
            </div>

            <div className="model-field-heading"><label id="model-name-label">模型名称</label><button type="button" className="reload-models" onClick={() => void discoverModels()} disabled={!canManage || busy === 'discover'}>{busy === 'discover' ? <LoaderCircle className="spin" /> : <RefreshCw />}加载模型</button></div>
            {serviceCapabilities.length > 0 && <section className="provider-service-capabilities" aria-label="ElevenLabs 完整能力">
              <header><strong>ElevenLabs 完整能力</strong><span>{serviceCapabilities.length}/14</span></header>
              <div className="provider-capability-filters">
                <button type="button" className={!activeCapability ? 'active' : ''} aria-pressed={!activeCapability} onClick={() => setActiveCapability('')}>
                  <span>全部模型</span><small>{models.length} 个模型</small>
                </button>
                {serviceCapabilities.map(capability => <button type="button" key={capability.id} title={capability.description} className={activeCapability === capability.id ? 'active' : ''} aria-pressed={activeCapability === capability.id} onClick={() => setActiveCapability(capability.id)}>
                  <span>{capability.label}</span>
                  <small>{capability.model_ids.length ? `${capability.model_ids.filter(modelId => models.some(model => model.model_id === modelId)).length} 个模型` : '独立服务'}</small>
                </button>)}
              </div>
              <p>点击能力分类筛选并选择模型；独立服务没有模型 ID，保存同一供应商模型后会自动调用对应接口。</p>
            </section>}
            <section className="model-selection-panel" role="group" aria-labelledby="model-name-label">
              <div className="model-selection-toolbar">
                <span>{models.length ? `已选择 ${selectedModels.length} 个模型` : '请先填写凭据并加载模型'}</span>
                {!!visibleModels.length && <button type="button" onClick={selectVisibleModels}>全选当前分类</button>}
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
                  : <div className="model-selection-empty"><span>{models.length ? '当前能力没有返回可选择的模型' : '尚未加载模型'}</span></div>}
            </section>
            {error && <div className="model-config-error" role="alert">{error}</div>}
            {notice && <div className="model-config-warning" role="status"><AlertTriangle size={17} />{notice}</div>}
            {message && <div className="model-config-success" role="status"><CheckCircle2 size={17} />{message}</div>}
          </div>

          <aside className="saved-models" aria-labelledby="saved-models-title">
            <div className="saved-models-heading">
              <div><h3 id="saved-models-title">已保存模型</h3><p>只有启用状态的模型会进入项目全局选择器。</p></div>
              <span aria-label="已保存模型数量">共 {savedModelRows.length} 个 · 已启用 {enabledSavedCount} 个</span>
            </div>
            {savedModelRows.length === 0
              ? <div className="saved-models-empty"><ShieldCheck /><span>当前分类尚未保存模型配置</span></div>
              : <div className="saved-model-list" aria-label={`${CATEGORY_META[category].label}已保存模型列表`}>
                {savedModelRows.map(({ configuration, model }) => (
                  <article className="saved-model-card" key={model.id}>
                    <div><strong>{model.display_name}</strong><span>{configuration.provider_label} · {model.subcategory ? AUDIO_LABELS[model.subcategory] : model.capabilities.includes('multimodal') ? '文本 + 多模态' : CATEGORY_META[category].label}</span><code>{model.model_id}</code></div>
                    <div className="saved-model-actions">
                      {model.enabled && onSelect && <button type="button" onClick={() => onSelect(category, model.model_id)}>设为当前</button>}
                      <button type="button" role="switch" aria-checked={model.enabled} aria-label={`${model.display_name} 全局启用`} className={`switch ${model.enabled ? 'on' : ''}`} disabled={!canManage || busy === model.id} onClick={() => void toggleModel(configuration, model)}><span /></button>
                      <button type="button" className="saved-model-delete" aria-label={`${model.display_name} 删除保存`} title="删除已保存模型" disabled={!canManage || busy === `delete:${model.id}`} onClick={() => void deleteModel(configuration, model)}>{busy === `delete:${model.id}` ? <LoaderCircle className="spin" /> : <X />}</button>
                    </div>
                  </article>
                ))}
              </div>}
          </aside>
        </div>

        <footer className="model-config-footer">
          <button type="button" className="connection-test" onClick={() => void testConnection()} disabled={!canManage || Boolean(busy)}>连接测试</button>
          <div><button type="button" className="cancel-model-config" onClick={closeDialog}>取消</button><button type="button" className="save-model-config" onClick={() => void save()} disabled={!canManage || Boolean(busy)}>{busy === 'save' && <LoaderCircle className="spin" />}保存配置</button></div>
        </footer>
      </section>
    </div>
  );
}
