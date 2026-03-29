from database import close_database, db_get, db_run, init_database


def clear_labels_data() -> None:
	"""Clear current label state and relabel history."""
	init_database()

	# Keep the canonical row (id=1) but clear its label and saved ESP windows.
	db_run(
		(
			"UPDATE labels "
			"SET name = ?, esp1 = NULL, esp2 = NULL, esp3 = NULL, "
			"esp4 = NULL, esp5 = NULL, esp6 = NULL, esp7 = NULL "
			"WHERE id = 1"
		),
		[""],
	)

	# Remove any extra rows and all relabel audit/history records.
	db_run("DELETE FROM labels WHERE id != 1")
	db_run("DELETE FROM relabels")

	current = db_get("SELECT id, name FROM labels WHERE id = 1")
	relabel_count = db_get("SELECT COUNT(*) AS count FROM relabels")

	print("Labels cleared successfully.")
	print(f"Current label row: {current}")
	print(f"Relabel entries remaining: {relabel_count['count'] if relabel_count else 0}")


if __name__ == "__main__":
	try:
		clear_labels_data()
	except Exception as error:
		print(f"Failed to clear labels: {error}")
		raise
	finally:
		close_database()
