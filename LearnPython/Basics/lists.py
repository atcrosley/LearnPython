# len - length
# dict - dictonary allows you to associate something with someone else
# list of dictonaries
students = ["Hermione", "Harry", "Ron"]

print(students[0])

for student in students:
    print(student)

for i in range(len(students)):
    print(i + 1, students[i])

students = {
    "Hermione": "Gryffindor",  # "key on left side" and value on right
    "Harry": "Gryffindor",
    "Ron": "Gryffindor",
    "Draco": "Slytherin"
}
print(students["Ron"])

for student in students:
    print(student, students[student], sep=", ")

students = [
    {"name": "Hermione", "house": "Gryffindor", "patronous": "Otter"},
    {"name": "Harry", "house": "Gryffindor", "patronous": "Stag"},
    {"name": "Draco", "house": "Slytherin", "patronous": None}
]
for student in students:
    print(student["name"], student["house"], student["patronous"])
