extends Node

var display_translation: Translation

func _enter_tree() -> void:
	var file := FileAccess.open("res://glk_patch/messages.json", FileAccess.READ)
	if file == null:
		push_error("Chinese display dictionary unavailable")
		return
	var data = JSON.parse_string(file.get_as_text())
	if not data is Dictionary:
		push_error("Chinese display dictionary invalid")
		return
	display_translation = preload("res://glk_patch/glk_display_translation.gd").new()
	display_translation.configure(data)
	TranslationServer.add_translation(display_translation)
	TranslationServer.set_locale("zh_CN")
	if "--glk-probe" in OS.get_cmdline_user_args():
		print("GLK_DISPLAY_READY ", data.get("exact", {}).size())

func _exit_tree() -> void:
	# 自定义 Translation 的脚本需在语言服务器释放前注销。
	if display_translation != null:
		TranslationServer.remove_translation(display_translation)
		display_translation = null
