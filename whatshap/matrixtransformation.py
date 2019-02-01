from collections import defaultdict
import sys
from .graph import ComponentFinder
from .core import Read, ReadSet, CoreAlgorithm, StaticSparseGraph
from .readscoring import score, partial_scoring, locality_sensitive_score
import logging
import pysam
import itertools

logger = logging.getLogger(__name__)

class MatrixTransformation:
	"""
	Construct transformed matrix by computing clusterings for each variant positon.
	"""
	def __init__(self, reads, position_to_component, ploidy, errorrate, min_overlap):
		"""
		reads -- ReadSet with reads to be considered
		position_to_component -- dict mapping variant positions to connected components
		ploidy -- the ploidy of the data
		errorrate -- read error rate
		min_overlap -- minimum required overlap of two reads
		"""
		# readset containing all reads of current connected component
		self._component_reads = None
		# set of reads covering current position
		self._current_column = None
		# cluster matrix aka transformed matrix
		self._cluster_matrix = ReadSet()
		# current mapping: read_name -> Read() object containing assignment to partitions
		self._readname_to_partitions = {}
		# number of clusters in each column
		self._number_of_clusters = []

		# map component_id -> read_ids
		connected_components = defaultdict(list)
		for i,read in enumerate(reads):
			position = read[0].position
			component_id = position_to_component[position]
			connected_components[component_id].append(i)
		# consider connected components separately
		for component_id, component in connected_components.items():
			# get reads belonging to this component
			self._component_reads = reads.subset(component)
			# create new Read objects that hold the cluster assignments
			self._readname_to_partitions = {}
			for read in self._component_reads:
				self._readname_to_partitions[read.name] = Read(read.name, read.mapqs[0], read.source_id, read.sample_id)
			# current column
			self._current_column = []
			# get all positions in this component
			component_positions = self._component_reads.get_positions()
			num_clusters = []
			#print(component_positions)
			#print(str(len(component_positions)))
			for j, position in enumerate(component_positions):
				self._current_column = []
				# get all reads that cover current position
				for i,read in enumerate(self._component_reads):
					if position in read:
						self._current_column.append( (i, read) )		
				if len(self._current_column) == 0:
					continue
				column = self._component_reads.subset([r[0] for r in self._current_column])

				# compute similarities for reads in column
				if 0.0 <= errorrate < 1.0:
					similarities = score(column, ploidy, errorrate, min_overlap)
				else:
					similarities = locality_sensitive_score(column, ploidy, min_overlap)
				
				# create read graph object
				graph = StaticSparseGraph(len(column))
	
				# insert edges into read graph
				for (read1, read2) in similarities:
					graph.addEdge(read1, read2, similarities.get(read1, read2))
				
				# run cluster editing
				clusterediting = CoreAlgorithm(graph)
				readpartitioning = clusterediting.run()
				num_clusters.append(len(readpartitioning))
				
				#readpartitioning = k_clustify(partial_scoring(similarities, index_set), readpartitioning, ploidy)

				# store the result in final MEC matrix
#				print('')
#				print(similarities)
#				print(position)
#				print(readpartitioning)
				for c,cluster in enumerate(readpartitioning):
#					print('cluster: ', c, cluster)
					for read_id in cluster:
						# get readname
						read_name = column[read_id].name
#						print(read_name, read_id)
						quality = [10] * max(ploidy,len(readpartitioning))
						quality[c] = 0
						self._readname_to_partitions[read_name].add_variant(position, c, quality)
				self._number_of_clusters.append(max(ploidy,len(readpartitioning)))
				
			avg_clusters = sum(num_clusters)/len(component_positions)
			lt_k = sum([1 for cluster in num_clusters if cluster > ploidy])
			ht_k = sum([1 for cluster in num_clusters if cluster < ploidy])
			#logger.info("Transformed matrix of "+str(len(num_clusters))+" clustering with "+str(sum(num_clusters)/len(component_positions))+" clusters on average ("++" < k, "++" > k)")
			logger.info("Transformed matrix of {} clustering with {} clusters on average ({} < k, {} > k)".format(len(num_clusters), avg_clusters, lt_k, ht_k))
			#print("Num Clusterings:  "+str(len(num_clusters)))
			#print("Avg Num clusters: "+str(sum(num_clusters)/len(component_positions)))
			#print("Clusters > k    : "+str(sum([1 for cluster in num_clusters if cluster > ploidy])))
			#print("Clusters < k    : "+str(sum([1 for cluster in num_clusters if cluster < ploidy])))
			
			# add the computed reads to final ReadSet
			for read in self._readname_to_partitions.values():
				if len(read) > 0:
					self._cluster_matrix.add(read)
		# sort readsets
		self._cluster_matrix.sort()
#		print('')

	def get_transformed_matrix(self):
		"""
		Return the readset which represents the transformed matrix.
		"""
		for read in self._cluster_matrix:
			prev = -1
			for var in read:
				if var.position == prev:
					print('DOUBLE: ',read)
				prev = var.position
		return self._cluster_matrix

	def get_cluster_counts(self):
		"""
		Return the number of clusters per column in the cluster matrix.
		"""
		return self._number_of_clusters
