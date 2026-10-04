extends Translation

var lookup: Dictionary = {}
var rules: Array = []
var anchors: Dictionary = {}
var prefixes: Array = []
var compiled: Dictionary = {}
var cache: Dictionary = {}
var tag_pattern := RegEx.create_from_string("\\[[^\\]\\n]*\\]")
var segment_pattern := RegEx.create_from_string("[^\\[\\]\\n（）()　：]+")
var image_pattern := RegEx.create_from_string("\\[img(?:=[^\\]]*)?\\][\\s\\S]*?\\[/img\\]")
var japanese_pattern := RegEx.create_from_string("[\u3041-\u30fa\u3400-\u9fff]")
var kana_pattern := RegEx.create_from_string("[\u3041-\u30fa]")
var list_separator := RegEx.create_from_string("[・／ ]")

func configure(data: Dictionary) -> void:
	lookup = data.get("exact", {})
	rules = data.get("rules", [])
	anchors = data.get("anchors", {})
	prefixes = data.get("prefixes", [])
	compiled.clear()
	cache.clear()
	locale = "zh_CN"

func _get_message(source: StringName, _context: StringName) -> StringName:
	return StringName(_translate_display(str(source)))

func _translate_display(text: String, depth: int = 0) -> String:
	if depth >= 6:
		return ""
	if lookup.has(text):
		return StringName(lookup[text])
	# 部分游戏给按钮文字拼接留白或悬停箭头；只匹配配置的已知前缀后的完整词条，
	# 不放开短词子串替换，以免误改其他词或用户输入。
	for prefix in prefixes:
		if text.begins_with(prefix):
			var body := text.substr(prefix.length())
			if lookup.has(body):
				return StringName(prefix + str(lookup[body]))
	if text.contains("\n"):
		var lines := text.split("\n")
		var vertical := lines.size() > 2
		for line in lines:
			vertical = vertical and line.length() == 1
		if vertical:
			var joined := "".join(lines)
			return StringName("\n".join(str(lookup[joined]).split(""))) if lookup.has(joined) else StringName()
	if cache.has(text):
		return StringName(cache[text])
	var shallow := depth <= 2
	var candidates: Dictionary = {}
	for i in range(text.length()):
		for id in anchors.get(text.substr(i, 2), []) + anchors.get(text.substr(i, 1), []):
			candidates[int(id)] = true
	var tags := tag_pattern.search_all(text)
	var matches: Array = []
	var images := image_pattern.search_all(text)
	# 短词只允许占满标签/换行之间的可见片段，不进入词内部或图片资源地址。
	for segment in segment_pattern.search_all(text):
		var body := segment.get_string()
		if not lookup.has(body) or str(lookup[body]) == body:
			continue
		var protected := false
		for span in tags + images:
			if segment.get_start() < span.get_end() and segment.get_end() > span.get_start():
				protected = true
				break
		if not protected:
			matches.append({"start": segment.get_start(), "end": segment.get_end(), "replacement": str(lookup[body]), "id": -1})
	for id in candidates:
		if not compiled.has(id):
			compiled[id] = RegEx.create_from_string(rules[id].pattern)
		for found in compiled[id].search_all(text):
			var inside_tag := false
			for tag in tags + images:
				if (found.get_start() > tag.get_start() and found.get_start() < tag.get_end()) or (found.get_end() > tag.get_start() and found.get_end() < tag.get_end()):
					inside_tag = true
					break
			if not inside_tag:
				matches.append({"start": found.get_start(), "end": found.get_end(), "match": found, "id": id})
	matches.sort_custom(func(a, b):
		if a.start != b.start:
			return a.start < b.start
		if a.end != b.end:
			return a.end > b.end
		var a_specificity := int(rules[a.id].get("specificity", 0)) if a.id >= 0 else 1000000
		var b_specificity := int(rules[b.id].get("specificity", 0)) if b.id >= 0 else 1000000
		if a_specificity != b_specificity:
			return a_specificity > b_specificity
		if a.has("match") and b.has("match") and a.match.get_group_count() != b.match.get_group_count():
			return a.match.get_group_count() < b.match.get_group_count()
		return a.id < b.id)
	var output := ""
	var cursor := 0
	for entry in matches:
		if entry.start < cursor:
			continue
		output += text.substr(cursor, entry.start - cursor)
		if entry.has("replacement"):
			output += entry.replacement
		else:
			for part in rules[entry.id].parts:
				if part is String:
					output += part
					continue
				var value: String = entry.match.get_string(int(part))
				var attribute := false
				for span in tags + images:
					if entry.match.get_start(int(part)) >= span.get_start() and entry.match.get_end(int(part)) <= span.get_end():
						attribute = true
						break
				var translated := _translate_display(value, depth + 1) if not attribute and value.length() < text.length() else ""
				output += translated if not translated.is_empty() else value
		cursor = entry.end
	output += text.substr(cursor)
	# 整句模板优先；仅当结果仍留有已知原文词条时，才改按标签、全角空格、冒号或「・」等分隔的片段逐段转换。
	var leftover := _untranslated_pieces(output)
	if leftover > 0:
		var segmented := _translate_segments(text, depth)
		if not segmented.is_empty() and _untranslated_pieces(segmented) < leftover:
			output = segmented
			leftover = _untranslated_pieces(segmented)
		var source_lines := text.split("\n")
		var output_lines := output.split("\n")
		if leftover > 0 and source_lines.size() > 1 and output_lines.size() == source_lines.size() and depth + 1 < 6:
			# 多行日志：逐行比较，只有单行转换后残留更少才替换该行，不连累整句模板已译好的行。
			for index in source_lines.size():
				if _untranslated_pieces(output_lines[index]) == 0:
					continue
				var converted := str(_translate_display(source_lines[index], depth + 1))
				if not converted.is_empty() and _untranslated_pieces(converted) < _untranslated_pieces(output_lines[index]):
					output_lines[index] = converted
			output = "\n".join(output_lines)
	if output == text:
		output = ""
	# 递归深处受深度上限截断的结果可能不完整，不写缓存，免得顶层调用复用残缺结果。
	if shallow:
		if cache.size() >= 8192:
			cache.clear()
		cache[text] = output
	return StringName(output)

func _untranslated_pieces(output: String) -> int:
	if japanese_pattern.search(output) == null:
		return 0
	var count := 0
	for piece in segment_pattern.search_all(tag_pattern.sub(output, "\n", true)):
		for part in list_separator.sub(piece.get_string(), "\n", true).split("\n"):
			if kana_pattern.search(part) != null or (lookup.has(part) and str(lookup[part]) != part):
				count += 1
	return count

func _translate_segments(text: String, depth: int) -> String:
	var pieces := segment_pattern.search_all(text)
	if pieces.is_empty():
		return ""
	if pieces.size() == 1 and pieces[0].get_string() == text:
		return _translate_list(text, depth, true)
	var spans := tag_pattern.search_all(text) + image_pattern.search_all(text)
	var output := ""
	var cursor := 0
	for piece in pieces:
		var body := piece.get_string()
		var inside := false
		for span in spans:
			if piece.get_start() < span.get_end() and piece.get_end() > span.get_start():
				inside = true
				break
		if inside or japanese_pattern.search(body) == null:
			continue
		# 紧贴样式标签的片段多为模板的一部分（变量被上色），只接受完整词条，不单独套模板。
		var styled := (piece.get_start() > 0 and text[piece.get_start() - 1] == "]") or (piece.get_end() < text.length() and text[piece.get_end()] == "[")
		var translated := _translate_piece(body, depth, not styled)
		if translated.is_empty():
			return ""
		output += text.substr(cursor, piece.get_start() - cursor) + translated
		cursor = piece.get_end()
	output += text.substr(cursor)
	return output if output != text else ""

func _translate_piece(body: String, depth: int, allow_rules: bool) -> String:
	if lookup.has(body):
		return str(lookup[body])
	var listed := _translate_list(body, depth, allow_rules)
	if not listed.is_empty():
		return listed
	if not allow_rules or depth + 1 >= 6:
		return ""
	var translated := str(_translate_display(body, depth + 1))
	return translated if kana_pattern.search(translated) == null else ""

func _translate_list(body: String, depth: int, allow_rules: bool) -> String:
	var separators := list_separator.search_all(body)
	if separators.is_empty():
		return ""
	# 以分隔符切分，优先匹配最长的已知词条（词条本身可能含分隔符）。
	var starts: Array = [0]
	var ends: Array = []
	for separator in separators:
		ends.append(separator.get_start())
		starts.append(separator.get_end())
	ends.append(body.length())
	var output := ""
	var i := 0
	while i < starts.size():
		var done := false
		for j in range(starts.size() - 1, i - 1, -1):
			var candidate := body.substr(starts[i], ends[j] - starts[i])
			if candidate.is_empty() and j == i:
				done = true
			elif lookup.has(candidate):
				output += str(lookup[candidate])
				done = true
			elif j == i:
				if japanese_pattern.search(candidate) == null:
					output += candidate
					done = true
				elif allow_rules and depth + 1 < 6:
					var translated := str(_translate_display(candidate, depth + 1))
					if not translated.is_empty() and kana_pattern.search(translated) == null:
						output += translated
						done = true
			if done:
				if j + 1 < starts.size():
					output += body.substr(ends[j], starts[j + 1] - ends[j])
				i = j + 1
				break
		if not done:
			return ""
	return output
