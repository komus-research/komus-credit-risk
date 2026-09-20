"""Pure deterministic consumer of ``DatasetInspectionReport``."""
from __future__ import annotations
from collections import Counter, defaultdict
from copy import deepcopy
import re
import unicodedata
from typing import Any
from komus_risk.data.inspection import ColumnInspection, DatasetInspectionReport
from komus_risk.hashing import stable_hash
from .contracts import ColumnRoleProposal, ConfidenceLevel, DatasetPreparationProposal, PositiveClassCandidate, PredictorEligibility, ProposalItem, ProposalWarning, ProposedColumnRole, ProposedTechnicalGroup, WarningSeverity

DEFAULT_POLICY: dict[str, Any] = {
 "policy_id":"tabular-preparation-analyzer", "policy_version":"1", "name_normalization":"NFKC/trim/camel-and-digit-boundaries/separator-split/casefold",
 "tokens":{"target":("target","label","class","outcome","response","event","flag","mark","y","цель","метка","класс","исход","событие","флаг"),"identifier":("id","identifier","key","uuid","guid","inn","ogrn","snils","ид","идентификатор","ключ","инн","огрн"),"suffix":("norm","normalized","scaled","std","standardized","encoded"),"group_stop":("id","identifier","key","target","label","class","flag","mark","norm","normalized","scaled","std","standardized","encoded","value","val","feature","column","data")},
 "score_bounds":(0,1000), "target":{"gate_non_null":2,"gate_unique":2,"base":400,"name_bonus":300,"identifier_penalty":-300,"missing":((0,150,"no_missing_values"),(.05,100,"low_missingness"),(.20,50,"moderate_missingness")),"support":((5,100,"class_support_at_least_5"),(2,50,"class_support_at_least_2")),"canonical_boolean_pairs":(("0","1"),("false","true"),("no","yes"),("n","y"),("нет","да")),"boolean_bonus":50,"candidate_threshold":400,"confidence":(800,600)},
 "identifier":{"gate_non_null":2,"gate_unique_fraction":.95,"uniqueness":((1,350,"exact_unique_values"),(.995,320,"very_high_unique_fraction"),(.98,280,"near_unique_fraction"),(.95,200,"identifier_candidate_unique_fraction")),"name_bonus":350,"missing":((0,150,"no_missing_values"),(.01,100,"very_low_missingness"),(.05,50,"low_missingness")),"representation_bonus":100,"penalties":{"target_token":-250,"datetime":-250,"fractional":-200,"long_text":-200},"long_text_length":64,"candidate_threshold":450,"confidence":(800,600)},
 "structural":{"near_unique_non_null":20,"near_unique_percent":98,"high_cardinality_non_null":20,"high_cardinality_unique":50,"high_cardinality_fraction":.5},
 "proxy":{"target_min_score":600,"minimum_overlap":50,"minimum_coverage":.8,"minimum_accuracy":.995,"minimum_category_support":5,"deterministic_source_max_unique_fraction":.20}, "groups":{"minimum_members":2,"minimum_token_length":3,"structural_score":900,"repeated_score":700,"logical_type_score":500,"kind_order":{"structural_prefix":0,"repeated_token":1,"logical_type":2,"fallback":3}}, "analysis_state":{"requires_non_null_value":True},
 "predictor":{"missingness_review_fraction":.5}, "role":{"conflict_score_difference":150,"precedence":("exclude","conflict","proxy_warning","target","identifier","feature","unknown")}, "sorting":{"positive_class":("bool","integer","float","string","datetime","other"),"target":("score_desc","missing_asc","minimum_class_desc","normalized_name_asc","position_asc"),"identifier":("score_desc","unique_fraction_desc","missing_asc","normalized_name_asc","position_asc"),"warnings":("severity","position","code","target_rank"),"warning_severity":("WARNING","INFO"),"groups":("kind","key")},
 "reason_text":{"binary_cardinality":"Найдены ровно два непустых значения.","target_name_token":"Название содержит слово, характерное для целевого показателя.","identifier_name_penalty":"Название содержит слово, характерное для идентификатора.","no_missing_values":"Пропусков нет.","low_missingness":"Есть небольшая доля пропусков.","moderate_missingness":"Есть пропуски.","class_support_at_least_5":"Каждый класс представлен минимум пятью строками.","class_support_at_least_2":"Каждый класс представлен минимум двумя строками.","canonical_boolean_pair":"Значения похожи на каноническую булеву пару.","exact_unique_values":"Все непустые значения уникальны.","very_high_unique_fraction":"Почти все значения уникальны.","near_unique_fraction":"Значения почти уникальны.","identifier_candidate_unique_fraction":"Высокая доля уникальных значений.","identifier_name_token":"Название содержит слово, характерное для идентификатора.","very_low_missingness":"Доля пропусков очень мала.","identifier_compatible_representation":"Техническое представление совместимо с идентификатором.","target_name_penalty":"Название также похоже на целевой показатель.","datetime_penalty":"Дата и время требуют отдельной проверки семантики.","fractional_numeric_penalty":"Дробные числовые значения менее типичны для идентификатора.","long_text_penalty":"Длинный свободный текст менее типичен для идентификатора.","all_missing_column":"Колонка полностью состоит из пропусков.","constant_column":"Колонка содержит одно непустое значение.","near_unique_column":"Значения колонки почти уникальны.","missing_values_present":"В колонке есть пропуски.","high_missingness":"В колонке высокая доля пропусков.","almost_empty_column":"Колонка почти пуста.","mixed_value_types":"В колонке смешаны разные типы значений.","unknown_logical_type":"Логический тип колонки не удалось определить.","datetime_semantics_unconfirmed":"Семантика даты и времени не подтверждена.","high_cardinality_non_numeric":"Высокая кардинальность нечисловой колонки требует проверки.","no_target_candidate":"Подходящая цель не найдена.","multiple_target_candidates":"Найдено несколько возможных целей.","no_identifier_candidate":"Подходящий идентификатор не найден.","multiple_identifier_candidates":"Найдено несколько возможных идентификаторов.","target_candidate_has_missing_values":"В предполагаемой цели есть пропуски.","target_identifier_role_ambiguity":"Колонка одновременно похожа на цель и идентификатор; требуется проверка.","potential_target_proxy":"Колонка почти полностью соответствует предполагаемой цели; проверьте происхождение и момент доступности.","potential_deterministic_target_proxy":"Категории колонки почти детерминированно соответствуют предполагаемой цели; проверьте происхождение и момент доступности.","insufficient_evidence":"В файле недостаточно непустых значений для формирования предложений."}
}

def _tokens(name: str) -> tuple[str, ...]:
 value=unicodedata.normalize("NFKC",name).strip(); value=re.sub(r"(?<=[a-zа-я])(?=[A-ZА-Я])"," ",value); value=re.sub(r"(?<=[A-Za-zА-Яа-я])(?=\d)|(?<=\d)(?=[A-Za-zА-Яа-я])"," ",value); return tuple(x for x in re.split(r"[_\-./\\\s]+",value.casefold()) if x)

class DatasetPreparationAnalyzer:
 def __init__(self, policy: dict[str, Any] | None=None) -> None:
  self.policy=deepcopy(DEFAULT_POLICY if policy is None else policy); self.policy_id=self.policy["policy_id"]; self.policy_version=self.policy["policy_version"]; self.policy_hash=stable_hash(self.policy)
 def analyze(self, report: DatasetInspectionReport) -> DatasetPreparationProposal:
  targets=sorted((x for c in report.columns if (x:=self._target(c))),key=lambda x:self._target_sort_key(x,report)); identifiers=sorted((x for c in report.columns if (x:=self._identifier(c))),key=lambda x:self._identifier_sort_key(x,report)); target_by={x.column_name:x for x in targets}; identifier_by={x.column_name:x for x in identifiers}; warnings=self._basic_warnings(report,targets,identifiers); warnings.extend(self._proxy_warnings(report,targets,identifier_by)); proxy_columns={w.column_name for w in warnings if w.code in {"potential_target_proxy","potential_deterministic_target_proxy"}}; roles=tuple(self._role(c,target_by.get(c.column_name),identifier_by.get(c.column_name),c.column_name in proxy_columns) for c in report.columns); positives=tuple(PositiveClassCandidate(t.column_name,c.value,None,ConfidenceLevel.UNDETERMINED) for t in targets for c in sorted(self._column(report,t.column_name).value_counts or (),key=lambda x:self._positive_key(x.value))); has_content=any(c.non_null_count for c in report.columns) if self.policy["analysis_state"]["requires_non_null_value"] else bool(report.columns)
  if not has_content: warnings.append(self._warning("insufficient_evidence",WarningSeverity.WARNING,None,None))
  return DatasetPreparationProposal(report.snapshot_fingerprint,report.inspection_policy_version,self.policy_id,self.policy_version,self.policy_hash,"READY" if has_content else "INSUFFICIENT_DATA",tuple(targets),positives,tuple(identifiers),roles,self._groups(report.columns),tuple(self._sort_warnings(warnings,targets)))
 def _reason(self,code:str)->str: return self.policy["reason_text"][code]
 def _warning(self,code:str,severity:WarningSeverity,name:str|None,position:int|None,evidence:dict[str,Any]|None=None)->ProposalWarning: return ProposalWarning(code,severity,name,position,(self._reason(code),),evidence or {})
 @staticmethod
 def _column(report:DatasetInspectionReport,name:str)->ColumnInspection: return next(c for c in report.columns if c.column_name==name)
 def _positive_key(self,value:Any)->tuple[int,Any]:
  if isinstance(value,bool): family="bool"; normalized=value
  elif isinstance(value,int): family="integer"; normalized=value
  elif isinstance(value,float): family="float"; normalized=value
  elif isinstance(value,str): family="string"; normalized=unicodedata.normalize("NFKC",value).casefold()
  else: family="other"; normalized=repr(value)
  return(self.policy["sorting"]["positive_class"].index(family),normalized)
 def _target_sort_key(self,item:ProposalItem,report:DatasetInspectionReport)->tuple[Any,...]:
  column=self._column(report,item.column_name); values={"score_desc":-item.score_points,"missing_asc":column.missing_count,"minimum_class_desc":-item.evidence["minimum_class_count"],"normalized_name_asc":_tokens(item.column_name),"position_asc":item.column_position}; return tuple(values[name] for name in self.policy["sorting"]["target"])
 def _identifier_sort_key(self,item:ProposalItem,report:DatasetInspectionReport)->tuple[Any,...]:
  column=self._column(report,item.column_name); values={"score_desc":-item.score_points,"unique_fraction_desc":-column.unique_fraction,"missing_asc":column.missing_count,"normalized_name_asc":_tokens(item.column_name),"position_asc":item.column_position}; return tuple(values[name] for name in self.policy["sorting"]["identifier"])
 def _confidence(self,score:int,family:str)->ConfidenceLevel:
  high,medium=self.policy[family]["confidence"]; return ConfidenceLevel.HIGH if score>=high else ConfidenceLevel.MEDIUM if score>=medium else ConfidenceLevel.LOW
 def _target(self,c:ColumnInspection)->ProposalItem|None:
  rule=self.policy["target"]; names=self.policy["tokens"]
  if c.non_null_count<rule["gate_non_null"] or c.unique_non_null_count!=rule["gate_unique"] or not c.value_counts:return None
  codes=["binary_cardinality"]; score=rule["base"]; found=set(_tokens(c.column_name))
  if found&set(names["target"]):score+=rule["name_bonus"];codes.append("target_name_token")
  if found&set(names["identifier"]):score+=rule["identifier_penalty"];codes.append("identifier_name_penalty")
  for maximum,points,code in rule["missing"]:
   if c.missing_fraction<=maximum:score+=points;codes.append(code);break
  minimum=min(x.count for x in c.value_counts)
  for support,points,code in rule["support"]:
   if minimum>=support:score+=points;codes.append(code);break
  pair={str(x.value).strip().casefold() for x in c.value_counts}
  if tuple(sorted(pair)) in {tuple(sorted(values)) for values in rule["canonical_boolean_pairs"]}:score+=rule["boolean_bonus"];codes.append("canonical_boolean_pair")
  lower,upper=self.policy["score_bounds"];score=max(lower,min(upper,score))
  if score<rule["candidate_threshold"]:return None
  return ProposalItem(c.column_name,c.column_position,"target_candidate",score,self._confidence(score,"target"),tuple(codes),tuple(self._reason(code) for code in codes),{"minimum_class_count":minimum,"missing_count":c.missing_count,"value_counts":tuple((x.value,x.count) for x in c.value_counts)})
 def _identifier(self,c:ColumnInspection)->ProposalItem|None:
  rule=self.policy["identifier"]; names=self.policy["tokens"]
  if c.non_null_count<rule["gate_non_null"] or c.unique_fraction<rule["gate_unique_fraction"] or c.is_constant or c.is_all_missing:return None
  codes=[];score=0;found=set(_tokens(c.column_name))
  for fraction,points,code in rule["uniqueness"]:
   if c.unique_fraction>=fraction:score+=points;codes.append(code);break
  if found&set(names["identifier"]):score+=rule["name_bonus"];codes.append("identifier_name_token")
  for maximum,points,code in rule["missing"]:
   if c.missing_fraction<=maximum:score+=points;codes.append(code);break
  p=c.representation_profile
  if c.inferred_logical_type in {"categorical","text"} or p.numeric_all_integral or p.string_all_digits:score+=rule["representation_bonus"];codes.append("identifier_compatible_representation")
  penalty=rule["penalties"]
  if found&set(names["target"]):score+=penalty["target_token"];codes.append("target_name_penalty")
  if c.inferred_logical_type=="datetime":score+=penalty["datetime"];codes.append("datetime_penalty")
  if p.numeric_has_fractional_values:score+=penalty["fractional"];codes.append("fractional_numeric_penalty")
  if c.inferred_logical_type=="text" and (p.median_string_length or 0)>rule["long_text_length"]:score+=penalty["long_text"];codes.append("long_text_penalty")
  lower,upper=self.policy["score_bounds"];score=max(lower,min(upper,score))
  if score<rule["candidate_threshold"]:return None
  return ProposalItem(c.column_name,c.column_position,"identifier_candidate",score,self._confidence(score,"identifier"),tuple(codes),tuple(self._reason(code) for code in codes),{"unique_fraction":c.unique_fraction,"missing_count":c.missing_count})
 def _basic_warnings(self,report:DatasetInspectionReport,targets:list[ProposalItem],identifiers:list[ProposalItem])->list[ProposalWarning]:
  result=[];struct=self.policy["structural"]
  for c in report.columns:
   for code in c.column_warnings:result.append(self._warning(code,WarningSeverity.WARNING,c.column_name,c.column_position))
   if c.inferred_logical_type=="datetime":result.append(self._warning("datetime_semantics_unconfirmed",WarningSeverity.WARNING,c.column_name,c.column_position))
   if c.non_null_count>=struct["high_cardinality_non_null"] and c.unique_non_null_count>=struct["high_cardinality_unique"] and c.unique_fraction>=struct["high_cardinality_fraction"] and c.inferred_logical_type in {"categorical","text","unknown"}:result.append(self._warning("high_cardinality_non_numeric",WarningSeverity.WARNING,c.column_name,c.column_position))
  if not targets:result.append(self._warning("no_target_candidate",WarningSeverity.WARNING,None,None))
  if len(targets)>1:result.append(self._warning("multiple_target_candidates",WarningSeverity.WARNING,None,None))
  if not identifiers:result.append(self._warning("no_identifier_candidate",WarningSeverity.INFO,None,None))
  if len(identifiers)>1:result.append(self._warning("multiple_identifier_candidates",WarningSeverity.WARNING,None,None))
  for target in targets:
   if self._column(report,target.column_name).missing_count:result.append(self._warning("target_candidate_has_missing_values",WarningSeverity.WARNING,target.column_name,target.column_position))
  return result
 def _proxy_warnings(self,report:DatasetInspectionReport,targets:list[ProposalItem],identifiers:dict[str,ProposalItem])->list[ProposalWarning]:
  result=[];rule=self.policy["proxy"]
  for rank,target in enumerate(targets):
   if target.score_points<rule["target_min_score"]:continue
   for block in report.relation_blocks:
    if block.binary_reference_column!=target.column_name or block.overlap_non_null_rows<rule["minimum_overlap"] or block.coverage_fraction<rule["minimum_coverage"]:continue
    source=self._column(report,block.source_column);joint=defaultdict(lambda:defaultdict(int))
    for item in block.joint_counts:joint[item.source_value][item.reference_value]+=item.count
    if source.unique_non_null_count==2:
     source_values=sorted(joint,key=repr);reference_values=sorted({value for values in joint.values() for value in values},key=repr)
     if len(source_values)!=2 or len(reference_values)!=2:continue
     accuracy=max(joint[source_values[0]][reference_values[0]]+joint[source_values[1]][reference_values[1]],joint[source_values[0]][reference_values[1]]+joint[source_values[1]][reference_values[0]])/block.overlap_non_null_rows
    else:accuracy=sum(max(values.values()) for values in joint.values())/block.overlap_non_null_rows
    code=None
    if source.unique_non_null_count==2 and accuracy>=rule["minimum_accuracy"]:code="potential_target_proxy"
    elif source.inferred_logical_type in {"categorical","boolean"} and source.unique_fraction<=rule["deterministic_source_max_unique_fraction"] and source.column_name not in identifiers and all(sum(values.values())>=rule["minimum_category_support"] for values in joint.values()) and accuracy>=rule["minimum_accuracy"]:code="potential_deterministic_target_proxy"
    if code:result.append(self._warning(code,WarningSeverity.WARNING,source.column_name,source.column_position,{"related_target_candidate":target.column_name,"related_target_rank":rank,"overlap_non_null_rows":block.overlap_non_null_rows,"coverage_fraction":block.coverage_fraction,"best_binary_bijection_accuracy":accuracy}))
  return result
 def _role(self,c:ColumnInspection,target:ProposalItem|None,identifier:ProposalItem|None,has_proxy_warning:bool)->ColumnRoleProposal:
  role_rule=self.policy["role"];conflict=bool(target and identifier and abs(target.score_points-identifier.score_points)<role_rule["conflict_score_difference"])
  predicates={"exclude":c.is_all_missing or c.is_constant,"conflict":conflict,"proxy_warning":has_proxy_warning,"target":bool(target and (conflict or not identifier or target.score_points>identifier.score_points)),"identifier":bool(identifier and (conflict or not target or identifier.score_points>=target.score_points)),"feature":c.inferred_logical_type!="unknown","unknown":True}; roles={"exclude":ProposedColumnRole.EXCLUDE_CANDIDATE,"conflict":ProposedColumnRole.REVIEW_REQUIRED,"proxy_warning":ProposedColumnRole.REVIEW_REQUIRED,"target":ProposedColumnRole.TARGET_CANDIDATE,"identifier":ProposedColumnRole.IDENTIFIER_CANDIDATE,"feature":ProposedColumnRole.FEATURE_CANDIDATE,"unknown":ProposedColumnRole.UNKNOWN}
  role=next(roles[name] for name in role_rule["precedence"] if predicates[name])
  struct=self.policy["structural"];review=bool(target or identifier or has_proxy_warning or c.is_near_unique or (c.non_null_count>=struct["high_cardinality_non_null"] and c.unique_non_null_count>=struct["high_cardinality_unique"] and c.unique_fraction>=struct["high_cardinality_fraction"] and c.inferred_logical_type in {"categorical","text","unknown"}) or c.missing_fraction>=self.policy["predictor"]["missingness_review_fraction"] or c.inferred_logical_type in {"unknown","datetime"} or c.representation_profile.mixed_value_types);eligibility=PredictorEligibility.NOT_RECOMMENDED_CANDIDATE if c.is_all_missing or c.is_constant else PredictorEligibility.REVIEW_REQUIRED if review else PredictorEligibility.ELIGIBLE_CANDIDATE if c.inferred_logical_type!="unknown" else PredictorEligibility.UNKNOWN
  return ColumnRoleProposal(c.column_name,c.column_position,role,eligibility,("target_identifier_role_ambiguity",) if conflict else ())
 def _groups(self,columns:tuple[ColumnInspection,...])->tuple[ProposedTechnicalGroup,...]:
  unassigned={c.column_name for c in columns};result=[];tokens=self.policy["tokens"];group=self.policy["groups"]
  def add(kind,key,names,score,confidence):
   members=tuple(c.column_name for c in columns if c.column_name in names)
   if len(members)>=group["minimum_members"]:result.append(ProposedTechnicalGroup(kind,key,members,score,confidence));unassigned.difference_update(members)
  stems=defaultdict(list)
  for c in columns:
   parts=list(_tokens(c.column_name));
   if parts and parts[-1] in tokens["suffix"]:parts.pop()
   if parts and parts[-1].isdigit():parts.pop()
   if parts:stems["_".join(parts)].append(c.column_name)
  for key,names in sorted(stems.items()):add("structural_prefix",key,names,group["structural_score"],ConfidenceLevel.HIGH)
  repeated=Counter(item for c in columns if c.column_name in unassigned for item in _tokens(c.column_name) if len(item)>=group["minimum_token_length"] and not item.isdigit() and item not in tokens["group_stop"])
  for token,_ in sorted(repeated.items(),key=lambda x:(-len(x[0]),-x[1],x[0])):add("repeated_token",token,[c.column_name for c in columns if c.column_name in unassigned and token in _tokens(c.column_name)],group["repeated_score"],ConfidenceLevel.MEDIUM)
  logical=defaultdict(list)
  for c in columns:
   if c.column_name in unassigned:logical[c.inferred_logical_type].append(c.column_name)
  for key,names in sorted(logical.items()):add("logical_type",key,names,group["logical_type_score"],ConfidenceLevel.LOW)
  if unassigned:add("fallback","other",unassigned,None,ConfidenceLevel.UNDETERMINED)
  return tuple(sorted(result,key=lambda x:(group["kind_order"][x.group_kind],x.group_key)))
 def _sort_warnings(self,items:list[ProposalWarning],targets:list[ProposalItem])->list[ProposalWarning]:
  rank={target.column_name:index for index,target in enumerate(targets)}; severity={value:index for index,value in enumerate(self.policy["sorting"]["warning_severity"])}
  def key(warning:ProposalWarning)->tuple[Any,...]:
   values={"severity":severity[warning.severity.value],"position":warning.column_position if warning.column_position is not None else -1,"code":warning.code,"target_rank":rank.get(warning.evidence.get("related_target_candidate"),-1)}; return tuple(values[name] for name in self.policy["sorting"]["warnings"])
  return sorted(items,key=key)
