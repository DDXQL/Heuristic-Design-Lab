"""Small provider pilot; demo H and train subset, never formal study assets."""

from collections import Counter
from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import re

from fjsp_usage.research.candidates import H_ARGS, validate_code, parse_response, CandidateError
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.prompts import build_prompt
from fjsp_usage.research.protocol import SearchConfig, digest
from llm4ad.task.optimization.fjsp_set import load_instance
from .budget import BudgetLedger, BudgetJournal, BudgetStop
from .config import ProviderConfig, fingerprint, loopback_url
from .real_transport import JsonCandidateTransport
from .runtime import evaluate
from .search import BudgetedSearch


@dataclass(frozen=True)
class PilotConfig:
    provider: ProviderConfig = field(default_factory=lambda: ProviderConfig(
        'https://api.deepseek.com/chat/completions', 'deepseek-flash',
        protocol='deepseek-chat-v1', api_key_env='DEEPSEEK_API_KEY',
        connect_timeout=10, read_timeout=60, total_timeout=90,
        max_output_tokens=2048, max_prompt_bytes=16384, input_token_reservation=32768,
        temperature=0.7, thinking='disabled', expected_response_model='deepseek-flash'))
    mode: str = 'real'
    real_requests_authorized: bool = True
    total_request_cap: int = 50
    total_token_cap: int | None = None
    cost_cap_estimate: float = 3.0
    input_price_per_million: float = 2.0
    output_price_per_million: float = 8.0
    price_source: str = 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/; 2026-10-08 CNY peak, cache discounts ignored'

    def payload(self):
        return asdict(self)

    def phase_caps(self):
        return {'probe': 1, 'h_samples': 6, 'u_init': 12, 'u_search': 10}

    def check_dispatch(self):
        if not self.real_requests_authorized:
            raise ValueError('真实请求尚未授权')
        if self.mode == 'synthetic':
            if not loopback_url(self.provider.endpoint) or self.provider.api_key_env:
                raise ValueError('离线验收只能使用本地服务且不能携带密钥')
        elif (self.mode != 'real' or self.provider.endpoint != 'https://api.deepseek.com/chat/completions'
              or self.provider.model != 'deepseek-flash' or self.provider.protocol != 'deepseek-chat-v1'
              or self.provider.thinking != 'disabled'):
            raise ValueError('此试跑仅支持锁定的官方 DeepSeek Flash 非思考配置')


def load_local_key(path):
    """Read one literal assignment, never source shell code or echo its value."""
    path = Path(path)
    if not path.exists():
        raise ValueError('本机密钥文件尚未创建：请先填写 .env.deepseek.local')
    lines = [line.strip() for line in path.read_text().splitlines()
             if line.strip() and not line.lstrip().startswith('#')]
    if len(lines) != 1 or not lines[0].startswith('DEEPSEEK_API_KEY='):
        raise ValueError('密钥文件只能包含一行 DEEPSEEK_API_KEY=完整密钥，可附加注释行')
    value = lines[0].split('=', 1)[1].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1]
    if not re.fullmatch(r'sk-[A-Za-z0-9_-]{12,}', value):
        raise ValueError('请在本机文件填写完整 sk- 密钥，不能使用星号遮挡值或占位文本')
    return value


def demo_members():
    return tuple(validate_code('def priority(' + ', '.join(H_ARGS) + '):\n    return ' + expression,
                               description=description, kind='h')
                 for expression, description in (
                     ('-earliest_finish', 'Demo EFT: prefer the smallest earliest finish.'),
                     ('-processing_time', 'Demo SPT: prefer the shortest processing time.')))


def input_metadata(root, *, synthetic=False):
    root = Path(root)
    tiny = root / 'experiments/tier2/offline_v1/tiny.fjsp'
    rows = [{'name': 'micro/tiny.fjsp', 'path': str(tiny),
             'sha256': hashlib.sha256(tiny.read_bytes()).hexdigest()}]
    if not synthetic:
        manifest = json.loads((root / 'data/fjsp_manifest.json').read_text())
        data_root = (root / manifest['portable_root']).resolve()
        for name in manifest['split']['train'][:3]:
            path = (data_root / name).resolve()
            if not path.is_relative_to(data_root):
                raise ValueError('train path escape')
            rows.append({'name': 'train/' + name, 'path': str(path),
                         'sha256': manifest['files'][name]['sha256']})
    return rows


class PilotJournal(BudgetJournal):
    def request(self, key, prompt, *, kind='U'):
        if key not in self.data['requests'] and self.ledger.data.get('pilot_stop_reason'):
            raise BudgetStop(self.ledger.data['pilot_stop_reason'])
        existed = key in self.data['requests']
        result = super().request(key, prompt, kind=kind)
        if result['status'] != 'completed' or result['usage'] is None:
            self.ledger.data['pilot_stop_reason'] = '接口失败或用量未知；停止后续请求，不自动重试'
            self.ledger.save()
        elif result.get('response_metadata', {}).get('reasoning_tokens', 0):
            self.ledger.data['pilot_stop_reason'] = '关闭思考后仍报告推理 token；停止并核实配置'
            self.ledger.save()
        if not existed:
            count = len(self.ledger.data['records'])
            if count == 1 or count % 5 == 0:
                print(f'DeepSeek 进度：{count}/50 次；阶段 {self.phase}', flush=True)
        return result


class PilotSearch(BudgetedSearch):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for attribute in ('initial_requests', 'evolution_requests'):
            previous = getattr(self, attribute)
            setattr(self, attribute, PilotJournal(previous.path, phase=previous.phase,
                    cap=previous.cap, transport=previous.transport, ledger=previous.ledger))


class DeepSeekPilot:
    def __init__(self, directory, *, root, config=None):
        self.root, self.directory = Path(root), Path(directory)
        self.config = config or PilotConfig()
        self.members = demo_members()
        self.inputs = input_metadata(root, synthetic=self.config.mode == 'synthetic')
        self.protocol = {'kind': 'deepseek-api-pilot-v1', 'config': self.config.payload(),
            'H_status': 'handwritten EFT/SPT demo H; generated h samples are NOT added to H',
            'H': [asdict(m) for m in self.members], 'inputs': self.inputs,
            'search': {'arm': 'P', 'seed': 101, 'N': 3, 'cross_parents': 2,
                       'generations': 1, 'attempts': 10, 'initialization_cap': 12},
            'phase_caps': self.config.phase_caps(), 'implementation': fingerprint(root),
            'validation_test_access': False, 'formal_experiment': False}
        self.context = digest(self.protocol)
        self.directory.mkdir(parents=True, exist_ok=True)
        protocol_path = self.directory / 'pilot_protocol.json'
        if protocol_path.exists() and digest(json.loads(protocol_path.read_text())) != self.context:
            raise ValueError('源码、配置或数据已变化；请新建试跑目录，不能强行恢复')
        atomic_json(protocol_path, self.protocol)
        self.ledger = BudgetLedger(self.directory/'budget.json', self.config, self.context)
        self.transport = None
        self.instances = None

    def client(self):
        if self.transport is None:
            self.transport = JsonCandidateTransport(self.config)
        return self.transport

    def evaluate(self, candidate):
        if self.instances is None:
            instances = []
            for row in self.inputs:
                path = Path(row['path'])
                if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
                    raise ValueError('试跑输入文件哈希不匹配')
                instances.append(load_instance(path))
                if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
                    raise ValueError('加载期间试跑输入改变')
            self.instances = tuple(instances)
        return evaluate(candidate, self.members, self.instances,
                        tuple(r['name'] for r in self.inputs), timeout=3)

    def sample(self, phase, count, kind):
        journal = PilotJournal(self.directory/(phase+'_requests.json'), phase=phase,
                  cap=count, transport=self.client(), ledger=self.ledger)
        path = self.directory/(phase+'_results.json')
        rows = json.loads(path.read_text()) if path.exists() else []
        for index in range(count):
            if index < len(rows):
                continue
            prompt = build_prompt('H' if kind == 'h' else 'B0', 'I1', (), self.members, kind=kind)
            if phase == 'probe':
                prompt += '\nFor this connection check, return the constant integer 0.'
            record = journal.request(f'{index:03d}', prompt, kind=kind)
            row = {'id': index, 'request_status': record['status'], 'valid': False}
            if record['status'] == 'completed':
                try:
                    candidate = parse_response(record['text'], kind=kind)
                    row.update(candidate=asdict(candidate), evaluation=self.evaluate(candidate))
                    row['valid'] = row['evaluation']['valid']
                except CandidateError as exc:
                    row['error'] = str(exc)
            else:
                row['error'] = record.get('error')
            rows.append(row)
            atomic_json(path, rows)
            if self.ledger.data.get('pilot_stop_reason'):
                raise BudgetStop(self.ledger.data['pilot_stop_reason'])
        return rows

    def run(self):
        stop = None
        try:
            print('阶段 2：1 次连通性与代码验证', flush=True)
            probe = self.sample('probe', 1, 'U')
            if not probe[0]['valid']:
                raise ValueError('连通性请求未产生可评价代码；停止，保留失败记录')
            print('阶段 3：最多 6 个独立 h 样本；集合仍为演示 EFT/SPT', flush=True)
            self.sample('h_samples', 6, 'h')
            print('阶段 4：U 初始化最多 12 次，单组 P 一代 10 次', flush=True)
            search = PilotSearch(self.directory/'P', arm='P',
                config=SearchConfig(3, 2, 10, 1, 12, 101, 3), members=self.members,
                evaluator=self.evaluate, transport=self.client(), context=self.context,
                init_phase='u_init', search_phase='u_search', ledger=self.ledger,
                experiment=self.config, training_names=tuple(r['name'] for r in self.inputs))
            result = search.run()
            atomic_json(self.directory/'search_result.json', result)
            if result['phase'] != 'completed':
                stop = result['phase']
        except (BudgetStop, ValueError) as exc:
            stop = str(exc)
        finally:
            if stop:
                self.ledger.data['pilot_stop_reason'] = stop
                self.ledger.save()
            report = self.report(stop)
        print('阶段 5：结果已保存至 ' + str(self.directory/'report.md'), flush=True)
        return report

    def report(self, stop=None):
        search = self.directory/'P/checkpoint.json'
        state = json.loads(search.read_text()) if search.exists() else None
        samples = {}
        for phase in ('probe', 'h_samples'):
            path = self.directory/(phase+'_results.json')
            rows = json.loads(path.read_text()) if path.exists() else []
            samples[phase] = {'attempts': len(rows), 'valid': sum(r['valid'] for r in rows)}
        summary = self.ledger.summary()
        cost = sum(row['cost_estimate'] for row in summary['phases'].values())
        result = {'kind': 'deepseek-api-pilot-v1', 'mode': self.config.mode,
                  'formal_experiment': False, 'validation_test_evaluated': False,
                  'H_status': self.protocol['H_status'], 'inputs': self.inputs,
                  'samples': samples, 'search_phase': state['phase'] if state else 'not_started',
                  'search_statuses': dict(Counter(r['status'] for r in state['attempts'])) if state else {},
                  'population': state['population'] if state else [], 'budget': summary,
                  'conservative_cost_estimate_CNY': cost,
                  'actual_provider_charge_CNY': None,
                  'stop_reason': stop or self.ledger.data.get('pilot_stop_reason')}
        if state and state['phase'] == 'initialization_failed' and not result['stop_reason']:
            result['stop_reason'] = 'initialization_failed'
        atomic_json(self.directory/'report.json', result)
        atomic_json(self.directory/'progress.json', result)
        text = (f'# DeepSeek API 探索试跑\n\n正式论文实验：否。validation/test 访问：否。\n\n'
                f'H：{result["H_status"]}\n\n请求槽位 {summary["request_slots"]}/50；'
                f'确认发送 {summary["confirmed_sends"]}；未知用量 {summary["unknown_usage_requests"]}。\n\n'
                f'按高峰费率、不计缓存优惠估算 {cost:.6f} 元；实际账单扣费尚未核实。'
                '请求数有硬上限，token 预留与 3 元停止线不是供应商账单硬限额。\n\n'
                f'代码验证：{samples}。搜索状态：{result["search_phase"]}；'
                f'候选状态：{result["search_statuses"]}。停止原因：{result["stop_reason"]}。\n\n'
                '逐实例 makespan、下界、归一化分数、可行性和确定性复核见 '
                'h_samples_results.json、P/checkpoint.json；请求 token、模型标识和耗时见 *_requests.json。\n'
                '这只是演示 H、一个微型实例和 train 前三个实例、单组 P、单种子一代探索，'
                '不能作为正式 EoH-S H 或四组论文实验结论。\n')
        (self.directory/'report.md').write_text(text)
        return result
