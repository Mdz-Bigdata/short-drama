import { t } from '../../i18n';


export type PaymentChannelName = 'alipay' | 'wechat';

export const channelLabel = (name: string): string => {
  if (name === 'alipay') return t('支付宝');
  if (name === 'wechat') return t('微信支付');
  if (name === 'sandbox') return t('沙箱');
  return t('未选择');
};
