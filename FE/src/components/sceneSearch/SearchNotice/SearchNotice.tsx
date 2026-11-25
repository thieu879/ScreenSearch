import React from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Info, SearchX, Clock } from 'lucide-react';
import './SearchNotice.css';

export type NoticeVariant = 'caveat' | 'empty' | 'outOfScope' | 'error';

interface SearchNoticeProps {
  variant: NoticeVariant;
  /** Verbatim from the API's `reason`, or a client-side message for `error`. */
  message: string;
  title?: string;
}

const ICON: Record<NoticeVariant, React.ComponentType<{ size?: number }>> = {
  caveat: AlertTriangle,
  empty: SearchX,
  outOfScope: Clock,
  error: Info,
};

function formatRejectionMessageVi(message: string): string {
  const countMatch = message.match(/It holds ([\d,]+)\s+keyframes\s+from\s+(\d+)\s+driving clips([^.]*)\./);
  const scoreMatch = message.match(/\(Best match\s+([0-9.]+)\s+against\s+a\s+([0-9.]+)\s+threshold\.\)/);

  let corpusDesc = 'Kho dữ liệu chỉ gồm một tập cố định các đoạn video lái xe đã thu thập sẵn.';
  if (countMatch) {
    const [, frames, clips, rawDesc] = countMatch;
    let descVi = '';
    if (rawDesc.includes('recorded in Boston and Singapore between July and November 2018')) {
      descVi = ' được ghi hình tại Boston và Singapore từ tháng 7 đến tháng 11 năm 2018 — ban ngày và ban đêm, đường ướt và đường khô, nhưng không có tuyết, không có đường nông thôn hay sa mạc và không có xe cứu hộ/khẩn cấp';
    } else if (rawDesc.trim()) {
      descVi = ` (${rawDesc.trim()})`;
    }
    corpusDesc = `Kho dữ liệu gồm ${frames} khung hình chính từ ${clips} đoạn video lái xe${descVi}.`;
  }

  const advice = 'Nếu bạn nghĩ cảnh này có trong kho, hãy thử mô tả đơn giản hơn: việc đối chiếu chấm điểm trên toàn bộ cụm từ, do đó chi tiết phụ có thể khiến kết quả thực tế bị tụt dưới ngưỡng.';
  const scorePart = scoreMatch
    ? ` (Khớp nhất ${scoreMatch[1]} so với ngưỡng ${scoreMatch[2]}.)`
    : '';

  return `Không có khung hình nào trong kho dữ liệu phù hợp với mô tả này. ${corpusDesc} ${advice}${scorePart}`;
}

function formatContradictionMessageVi(message: string): string {
  const match = message.match(/Nothing in this archive matches, and this one is certain rather than a close call:\s+([^.]+)\./);
  let clauseVi = '';
  if (match) {
    let clause = match[1];
    clause = clause.replace(/no frame is tagged time=night/g, 'không có khung hình nào gắn nhãn ban đêm');
    clause = clause.replace(/all ([\d,]+) are tagged time=day/g, 'toàn bộ $1 khung hình đều là ban ngày');
    clause = clause.replace(/no frame is tagged time=day/g, 'không có khung hình nào gắn nhãn ban ngày');
    clause = clause.replace(/all ([\d,]+) are tagged time=night/g, 'toàn bộ $1 khung hình đều là ban đêm');
    clauseVi = `: ${clause}`;
  }
  return `Không có khung hình nào trong kho dữ liệu phù hợp, và điều này là chắc chắn chứ không phải do ngưỡng tương đồng${clauseVi}. Đây là thông tin ghi nhận từ dữ liệu gốc khi nạp, không phải điểm tương đồng — vì vậy đổi cách diễn đạt cũng sẽ không tìm thấy cảnh này do kho dữ liệu không chứa.`;
}

function formatOutOfScopeMessageVi(message: string): string {
  const prefix = 'This search works on single frames, so it cannot find events that only exist across time.';
  const adviceTrigger = 'Try describing what would be visible in one moment instead';

  let whyClauseVi = '';
  if (message.includes(prefix)) {
    const afterPrefix = message.slice(message.indexOf(prefix) + prefix.length);
    const whyRaw = afterPrefix.includes(adviceTrigger)
      ? afterPrefix.slice(0, afterPrefix.indexOf(adviceTrigger)).trim()
      : afterPrefix.trim();

    if (whyRaw) {
      const motionMatch = whyRaw.match(/^(.*?)\s+is motion (?:across|over) time,?\s*not (?:one|a single) frame\.?$/i);
      if (motionMatch) {
        const subject = motionMatch[1].trim();
        const subjectLower = subject.toLowerCase();
        let subjectVi: string;
        if (subjectLower.includes('cutting into our lane') || subjectLower.includes('cutting in')) {
          subjectVi = 'Hành động tạt đầu xe (cutting into our lane)';
        } else if (subjectLower.includes('braking hard') || subjectLower.includes('braking')) {
          subjectVi = 'Hành động phanh xe (braking)';
        } else if (subjectLower.includes('overtaking')) {
          subjectVi = 'Hành động vượt xe (overtaking)';
        } else if (subjectLower.includes('turning')) {
          subjectVi = 'Hành động rẽ xe (turning)';
        } else if (subjectLower.includes('accelerating')) {
          subjectVi = 'Hành động tăng tốc (accelerating)';
        } else if (subjectLower.includes('changing lanes') || subjectLower.includes('lane change')) {
          subjectVi = 'Hành động chuyển làn (changing lanes)';
        } else {
          subjectVi = `Hành động "${subject}"`;
        }
        whyClauseVi = ` ${subjectVi} là chuyển động theo thời gian chứ không thể hiện qua một khung hình đơn lẻ.`;
      } else {
        whyClauseVi = ` ${whyRaw}`;
      }
    }
  }

  const baseDesc = 'Tìm kiếm này chỉ hoạt động trên từng khung hình tĩnh nên không thể tìm kiếm các sự kiện diễn ra theo thời gian (chuyển động).';
  const adviceVi = "Thay vào đó, hãy thử mô tả những gì quan sát được trong một thời điểm cụ thể — ví dụ: 'xe con ở trước trái' thay vì 'xe đang tạt đầu'.";

  return `${baseDesc}${whyClauseVi} ${adviceVi}`;
}

export const SearchNotice: React.FC<SearchNoticeProps> = ({ variant, message, title }) => {
  const { t, i18n } = useTranslation();
  const Icon = ICON[variant];

  const headings: Record<NoticeVariant, string> = {
    caveat: t('notice_caveat_title'),
    empty: t('notice_empty_title'),
    outOfScope: t('notice_outOfScope_title'),
    error: t('notice_error_title'),
  };

  // Helper to format backend reason into Vietnamese if current locale is 'vi'
  const displayMessage = React.useMemo(() => {
    if (i18n.language !== 'vi') return message;

    // Check if it matches out of scope (temporal) reason
    if (variant === 'outOfScope' || message.includes('This search works on single frames')) {
      return formatOutOfScopeMessageVi(message);
    }

    const parts: string[] = [];

    // Check if it matches contradiction reason
    if (message.includes('Nothing in this archive matches, and this one is certain')) {
      parts.push(formatContradictionMessageVi(message));
    } else if (message.includes('Nothing in this archive appears to match')) {
      // Check if it matches rejection reason
      parts.push(formatRejectionMessageVi(message));
    } else if (message.includes('These results may not be what you asked for')) {
      // Check if it matches low confidence note
      const match = message.match(/\(([0-9.]+)\s+against\s+a\s+([0-9.]+)\s+confidence threshold\)/);
      if (match) {
        const [, score, tau] = match;
        parts.push(t('notice_caveat_message_vi', { score, tau }));
      } else {
        parts.push('Các kết quả này có thể không đúng hoàn toàn với mô tả của bạn. Bạn nên kiểm tra kỹ lại trước khi sử dụng.');
      }
    }

    // Check if it has unsupported modifier note
    const modMatch = message.match(/The condition '([^']+)' could not be verified automatically/);
    if (modMatch) {
      parts.push(t('notice_modifier_unsupported_vi', { phrase: modMatch[1] }));
    }

    // Check if it has object relative note
    const objRelMatch = message.match(/One part of that query was not searched for: '([^']+)'/);
    if (objRelMatch) {
      parts.push(t('notice_object_relative_vi', { phrase: objRelMatch[1] }));
    }

    // Check if it has relaxation note
    const relaxMatch = message.match(/Nothing matched exactly, so the search was widened: ([^.]+)\./);
    if (relaxMatch) {
      parts.push(t('notice_relaxation_vi', { relaxed: relaxMatch[1] }));
    }

    if (parts.length > 0) {
      return parts.join(' ');
    }

    return message;
  }, [message, variant, i18n.language, t]);

  return (
    <div className={`search-notice search-notice--${variant}`} role={variant === 'error' ? 'alert' : 'status'}>
      <div className="search-notice__icon" aria-hidden="true">
        <Icon size={20} />
      </div>
      <div className="search-notice__body">
        <p className="search-notice__heading">{title ?? headings[variant]}</p>
        <p className="search-notice__message">
          {displayMessage}
        </p>
      </div>
    </div>
  );
};

export default SearchNotice;
