import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CheckCircle2, Eye, EyeOff, FileText, Image as ImageIcon, LoaderCircle,
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
  subcategory: 'asr' | 'tts' | 'bgm' | 'music' | null;
  capabilities: string[];
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
}

interface Props {
  open: boolean;
  role?: string;
  mustChangePassword?: boolean;
  onClose: () => void;
  onSelect?: (category: ModelCategory, modelId: string) => void;
}

const CATEGORY_META: Record<ModelCategory, { label: string; icon: typeof FileText }> = {
  text: { label: '文本模型', icon: FileText },
  image: { label: '图像模型', icon: ImageIcon },
  video: { label: '视频模型', icon: Video },
  audio: { label: '音频模型', icon: Mic2 },
};

const AUDIO_LABELS: Record<string, string> = {
  asr: 'ASR 语音识别', tts: 'TTS 配音', bgm: 'BGM / 音效', music: '音乐',
};


export function ModelConfigurationCenter({
  open,
  role = 'user',
  mustChangePassword = false,
  onClose,
  onSelect,
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
  const [selectedModel, setSelectedModel] = useState('');
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const providers = useMemo(
    () => providerGroups.find(group => group.category === category)?.providers ?? [],
    [providerGroups, category],
  );
  const savedForCategory = configurations.filter(item => item.category === category);
  const canManage = role === 'admin' && !mustChangePassword;

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
    setError('');
    try {
      const result = await apiRequest<{ items: DiscoveredModel[]; total: number }>(
        '/api/model-configurations/discover',
        { method: 'POST', body: JSON.stringify(requestPayload()) },
      );
      setModels(result.items);
      setSelectedModel(current => result.items.some(item => item.model_id === current) ? current : '');
      setMessage(result.total ? `已动态加载 ${result.total} 个可用模型` : '供应商没有返回当前分类的模型');
    } catch (reason) {
      setModels([]);
      setSelectedModel('');
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
    setSelectedModel('');
    setMessage('');
    setError('');
  };

  const testConnection = async () => {
    if (!selectedModel) { setError('请先从动态列表选择模型'); return; }
    setBusy('test'); setError(''); setMessage('');
    try {
      const result = await apiRequest<{ connected: boolean; message: string }>(
        '/api/model-configurations/test',
        { method: 'POST', body: JSON.stringify({ ...requestPayload(), selected_model_ids: [selectedModel] }) },
      );
      setMessage(result.message);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '连接测试失败');
    } finally { setBusy(''); }
  };

  const save = async () => {
    if (!selectedModel) { setError('请先选择模型'); return; }
    setBusy('save'); setError(''); setMessage('');
    try {
      const saved = await apiRequest<ModelConfiguration>('/api/model-configurations', {
        method: 'POST',
        body: JSON.stringify({ ...requestPayload(), selected_model_ids: [selectedModel] }),
      });
      setConfigurations(current => [...current.filter(item => item.id !== saved.id), saved]);
      setSummary(current => ({
        ...current,
        [category]: configurations.filter(item => item.category === category && item.id !== saved.id)
          .reduce((count, item) => count + item.models.filter(model => item.enabled && model.enabled).length, 0)
          + saved.models.filter(model => saved.enabled && model.enabled).length,
      }));
      setApiKey(''); setShowKey(false); setModels([]); setSelectedModel('');
      setMessage('配置已安全保存并全局生效');
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
      setSummary(current => ({ ...current, [category]: Math.max(0, current[category] + (updated.enabled ? 1 : -1)) }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '模型状态更新失败');
    } finally { setBusy(''); }
  };

  const closeDialog = () => {
    setApiKey('');
    setShowKey(false);
    setModels([]);
    setSelectedModel('');
    setMessage('');
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
              return <button key={key} type="button" role="tab" aria-selected={category === key} className={category === key ? 'active' : ''} onClick={() => { setCategory(key); setProvider(''); setBaseUrl(''); setModels([]); setSelectedModel(''); setMessage(''); setError(''); }}><Icon size={17} />{CATEGORY_META[key].label}</button>;
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

            <div className="model-field-heading"><label htmlFor="model-name">模型名称</label><button type="button" className="reload-models" onClick={() => void discoverModels()} disabled={!canManage || busy === 'discover'}>{busy === 'discover' ? <LoaderCircle className="spin" /> : <RefreshCw />}加载模型</button></div>
            <select id="model-name" aria-label="模型名称" value={selectedModel} onChange={event => setSelectedModel(event.target.value)} disabled={!models.length}>
              <option value="">{models.length ? '请选择动态发现的模型' : '请先填写凭据并加载模型'}</option>
              {models.map(item => <option value={item.model_id} key={`${item.model_id}:${item.subcategory ?? ''}`}>{item.display_name}{item.subcategory ? ` · ${AUDIO_LABELS[item.subcategory]}` : item.capabilities.includes('multimodal') ? ' · 多模态' : ''}</option>)}
            </select>
            {selectedModel && <p className="model-description">{models.find(item => item.model_id === selectedModel)?.description || '供应商未提供模型说明'}</p>}
            {error && <div className="model-config-error" role="alert">{error}</div>}
            {message && <div className="model-config-success" role="status"><CheckCircle2 size={17} />{message}</div>}
          </div>

          <aside className="saved-models" aria-labelledby="saved-models-title">
            <div><h3 id="saved-models-title">已保存模型</h3><p>只有启用状态的模型会进入项目全局选择器。</p></div>
            {savedForCategory.length === 0 ? <div className="saved-models-empty"><ShieldCheck /><span>当前分类尚未保存模型配置</span></div> : savedForCategory.flatMap(configuration => configuration.models.map(model => (
              <article className="saved-model-card" key={model.id}>
                <div><strong>{model.display_name}</strong><span>{configuration.provider_label} · {model.subcategory ? AUDIO_LABELS[model.subcategory] : model.capabilities.includes('multimodal') ? '文本 + 多模态' : CATEGORY_META[category].label}</span><code>{model.model_id}</code></div>
                <div className="saved-model-actions">
                  {model.enabled && onSelect && <button type="button" onClick={() => onSelect(category, model.model_id)}>设为当前</button>}
                  <button type="button" role="switch" aria-checked={model.enabled} aria-label={`${model.display_name} 全局启用`} className={`switch ${model.enabled ? 'on' : ''}`} disabled={!canManage || busy === model.id} onClick={() => void toggleModel(configuration, model)}><span /></button>
                </div>
              </article>
            )))}
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
